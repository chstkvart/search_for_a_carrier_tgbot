import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

AUTO = 'auto'
AVIA = 'avia'

TERMINAL = 'terminal'
ADDRESS = 'address'

PACKAGING_PROTECTIVE = 'protective'
PACKAGING_PALLET = 'pallet'
PACKAGING_NONE = 'none'

PACKAGING_TITLES = {
    PACKAGING_PROTECTIVE: 'Защитная транспортировочная упаковка',
    PACKAGING_PALLET: 'Палетирование',
    PACKAGING_NONE: 'Без упаковки',
}

MISSING_PICKUP = 'забор груза по адресу'
MISSING_DELIVERY = 'доставка до адреса'
MISSING_PACKAGING = {
    PACKAGING_PROTECTIVE: 'защитная упаковка (обрешётка)',
    PACKAGING_PALLET: 'палетирование',
}

PALLET_VOLUME_M3 = 1.5
PALLET_MAX_WEIGHT_KG = 1000


class CarrierError(Exception):
    """Ошибка, текст которой можно показать пользователю."""


class CarrierNotConfigured(CarrierError):
    pass


@dataclass
class Shipment:
    delivery_type: str
    from_city: str
    from_mode: str
    to_city: str
    to_mode: str
    packaging: str
    weight: float
    volume: float
    from_address: str = ''
    to_address: str = ''

    @property
    def side_m(self) -> float:
        """Сторона куба, равного по объёму грузу: габариты пользователь не вводит."""
        return round(max(self.volume, 0.001) ** (1 / 3), 2)

    @property
    def side_cm(self) -> int:
        return max(int(round(self.side_m * 100)), 1)

    @property
    def pallets_count(self) -> int:
        by_volume = self.volume / PALLET_VOLUME_M3
        by_weight = self.weight / PALLET_MAX_WEIGHT_KG
        return max(1, int(-(-max(by_volume, by_weight) // 1)))

    @property
    def ship_date(self) -> date:
        return date.today() + timedelta(days=1)


@dataclass
class PriceItem:
    name: str
    price: float


@dataclass
class Quote:
    carrier: str
    total: float
    items: list[PriceItem] = field(default_factory=list)
    days_min: int | None = None
    days_max: int | None = None
    tariff: str = ''
    note: str = ''
    # Что пользователь заказал, но ТК не смогла посчитать (MISSING_PICKUP, MISSING_DELIVERY, MISSING_PACKAGING).
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def days_text(self) -> str:
        if self.days_min is None and self.days_max is None:
            return 'не указан'
        lo = self.days_min if self.days_min is not None else self.days_max
        hi = self.days_max if self.days_max is not None else self.days_min
        if lo == hi:
            return f'{lo} дн.'
        return f'{lo}–{hi} дн.'


class BaseCarrier:
    code: str = ''
    name: str = ''
    supports_avia: bool = False
    # Имена настроек из .env; значения из админки имеют приоритет.
    login_setting: str = ''
    secret_setting: str = ''

    def __init__(self):
        self.default_name = self.name
        self.enabled = True
        self.position = 0
        self.contacts = ''
        self.admin_login = ''
        self.admin_secret = ''

    @property
    def login(self) -> str:
        return self.admin_login or (getattr(settings, self.login_setting, '') if self.login_setting else '')

    @property
    def secret(self) -> str:
        return self.admin_secret or (getattr(settings, self.secret_setting, '') if self.secret_setting else '')

    def is_configured(self) -> bool:
        return True

    def client(self, **kwargs) -> httpx.AsyncClient:
        kwargs.setdefault('timeout', settings.CARRIER_HTTP_TIMEOUT)
        kwargs.setdefault('follow_redirects', True)
        return httpx.AsyncClient(**kwargs)

    async def calculate(self, shipment: Shipment) -> Quote:
        raise NotImplementedError


def parse_days(text) -> tuple[int | None, int | None]:
    """'2 - 5' -> (2, 5); '3' -> (3, 3)."""
    numbers = [int(n) for n in re.findall(r'\d+', str(text or ''))]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def normalize_city(name: str) -> str:
    return ' '.join(name.lower().replace('ё', 'е').replace('г.', ' ').split())
