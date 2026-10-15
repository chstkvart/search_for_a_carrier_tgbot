import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field

from django.conf import settings

from . import texts
from .carriers import CARRIERS
from .carriers.base import AVIA, BaseCarrier, CarrierError, CarrierNotConfigured, Quote, Shipment
from .carriers.manual import CustomCarrier

logger = logging.getLogger(__name__)

ADMIN_REFRESH_SECONDS = 10
_admin_loaded_at = 0.0
_custom_carriers: list[BaseCarrier] = []


def ensure_admin_defaults():
    """Создаёт в базе недостающие встроенные тексты и ТК, чтобы их было видно в админке."""
    from .models import BotText, CarrierConfig

    BotText.objects.filter(key__isnull=False).exclude(key__in=texts.DEFAULT_TEXTS).delete()
    for position, (key, (title, text)) in enumerate(texts.DEFAULT_TEXTS.items()):
        BotText.objects.get_or_create(key=key, defaults={'title': title, 'text': text, 'position': position})
        BotText.objects.filter(key=key).update(title=title, place='')
    for position, carrier in enumerate(CARRIERS):
        CarrierConfig.objects.get_or_create(
            code=carrier.code, defaults={'name': carrier.default_name, 'position': position},
        )


async def refresh_admin_settings(force: bool = False):
    """Подтягивает правки из админки (не чаще раза в ADMIN_REFRESH_SECONDS)."""
    global _admin_loaded_at, _custom_carriers
    if not force and time.monotonic() - _admin_loaded_at < ADMIN_REFRESH_SECONDS:
        return
    from .models import BotText, CarrierConfig

    try:
        text_rows = [row async for row in BotText.objects.all()]
        config_rows = [row async for row in CarrierConfig.objects.all()]
    except Exception:
        logger.exception('Не удалось прочитать настройки из админки')
        return

    extra: dict[str, list[str]] = {}
    for row in text_rows:
        if not row.key and row.enabled and row.place and row.text.strip():
            extra.setdefault(row.place, []).append(row.text)
    texts.set_overrides({row.key: row.text for row in text_rows if row.key}, extra)

    configs = {row.code: row for row in config_rows if row.code}
    for carrier in CARRIERS:
        config = configs.get(carrier.code)
        carrier.name = (config.name.strip() if config else '') or carrier.default_name
        carrier.enabled = config.enabled if config else True
        carrier.position = config.position if config else 0
        carrier.contacts = config.contacts.strip() if config else ''
        carrier.admin_login = config.login.strip() if config else ''
        carrier.admin_secret = config.secret.strip() if config else ''

    custom = []
    for row in config_rows:
        if row.code or not row.name.strip():
            continue
        carrier = CustomCarrier(row.id, row.name.strip())
        carrier.enabled = row.enabled
        carrier.position = row.position
        carrier.contacts = row.contacts.strip()
        carrier.supports_avia = row.supports_avia
        custom.append(carrier)
    _custom_carriers = custom
    _admin_loaded_at = time.monotonic()


def active_carriers() -> list[BaseCarrier]:
    carriers = [*CARRIERS, *_custom_carriers]
    return sorted((c for c in carriers if c.enabled), key=lambda c: c.position)


@dataclass
class SearchResult:
    quotes: list[Quote] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    not_configured: list[str] = field(default_factory=list)


def _timeout() -> float:
    return settings.CARRIER_HTTP_TIMEOUT * 2


def _error_text(exc: Exception) -> str:
    if isinstance(exc, CarrierError):
        return str(exc) or 'ошибка расчёта'
    if isinstance(exc, asyncio.TimeoutError):
        return 'сервис не ответил вовремя'
    return 'сервис временно недоступен'


async def calculate_all(shipment: Shipment) -> SearchResult:
    result = SearchResult()
    carriers = []
    for carrier in active_carriers():
        if shipment.delivery_type == AVIA and not carrier.supports_avia:
            result.failures.append((carrier.name, 'авиаперевозки не выполняются'))
        elif not carrier.is_configured():
            result.not_configured.append(carrier.name)
        else:
            carriers.append(carrier)

    async def one(carrier):
        try:
            return await asyncio.wait_for(carrier.calculate(shipment), _timeout())
        except CarrierNotConfigured:
            result.not_configured.append(carrier.name)
        except Exception as exc:
            if not isinstance(exc, CarrierError):
                logger.exception('%s: ошибка расчёта', carrier.name)
            result.failures.append((carrier.name, _error_text(exc)))
        return None

    quotes = await asyncio.gather(*(one(c) for c in carriers))
    # Сначала полные расчёты, затем те, где ТК не смогла посчитать часть услуг (Quote.missing).
    result.quotes = sorted((q for q in quotes if q and q.total > 0), key=lambda q: (not q.is_complete, q.total))
    return result


async def save_request(telegram_user, shipment: Shipment, result: SearchResult):
    from .models import CalculationRequest

    await CalculationRequest.objects.acreate(
        telegram_id=telegram_user.id,
        username=telegram_user.username or '',
        params=asdict(shipment),
        results={
            'quotes': [asdict(q) for q in result.quotes],
            'failures': result.failures,
            'not_configured': result.not_configured,
        },
    )
