import re
import time

from .base import (
    ADDRESS, AVIA, MISSING_DELIVERY, MISSING_PACKAGING, MISSING_PICKUP, BaseCarrier, CarrierError, PriceItem, Quote, Shipment, normalize_city,
)

SITE = 'https://rustc.biz'
SCRIPT_URL = f'{SITE}/bitrix/templates/rustc/js/scripts.js'
CACHE_TTL = 6 * 3600

CITY_CODES = {
    'MSK': 'москва',
    'SPB': 'санкт-петербург',
    'NSK': 'новосибирск',
    'KRS': 'красноярск',
    'IRK': 'иркутск',
    'UU': 'улан-удэ',
    'CHT': 'чита',
}

# Строка тарифа: /*MSK - NSK*/ [min, 0.1-1.5 м3, 1.5-4.5 м3, >4.5 м3, 40-300 кг, 300-900 кг, >900 кг]
ROW_RE = re.compile(r'/\*\s*([A-Z]+)\s*-\s*([A-Z]+)\s*\*/\s*\[([^\]]+)\]')


class RtsCarrier(BaseCarrier):
    """ТК «РТС» (rustc.biz): тарифы берутся из таблицы калькулятора на сайте."""

    code = 'rts'
    name = 'РТС'
    supports_avia = False

    _prices: dict[tuple[str, str], list[float]] = {}
    _loaded_at: float = 0

    async def _load(self):
        if self._prices and time.time() - self._loaded_at < CACHE_TTL:
            return
        async with self.client() as client:
            resp = await client.get(SCRIPT_URL)
            resp.raise_for_status()

        prices = {}
        for src, dst, values in ROW_RE.findall(resp.text):
            if src in CITY_CODES and dst in CITY_CODES:
                prices[(CITY_CODES[src], CITY_CODES[dst])] = [float(v) for v in values.split(',') if v.strip()]
        if not prices:
            raise CarrierError('не удалось прочитать тарифы с сайта')

        RtsCarrier._prices = prices
        RtsCarrier._loaded_at = time.time()

    async def calculate(self, shipment: Shipment) -> Quote:
        if shipment.delivery_type == AVIA:
            raise CarrierError('авиаперевозки не выполняются')
        await self._load()
        tariff = self._prices.get((normalize_city(shipment.from_city), normalize_city(shipment.to_city)))
        if not tariff:
            raise CarrierError('направление не обслуживается')

        weight, volume = shipment.weight, shipment.volume
        if weight < 40 and volume < 0.1:
            price, basis = tariff[0], 'минимальная стоимость'
        elif volume and weight / volume <= 200:
            col = 1 if volume < 1.5 else 2 if volume < 4.5 else 3
            price, basis = volume * tariff[col], f'{volume:g} м³ × {tariff[col]:g} ₽'
        else:
            col = 4 if weight < 300 else 5 if weight < 900 else 6
            price, basis = weight * tariff[col], f'{weight:g} кг × {tariff[col]:g} ₽'
        if price < tariff[0]:
            price, basis = tariff[0], 'минимальная стоимость'

        missing = []
        if shipment.from_mode == ADDRESS:
            missing.append(MISSING_PICKUP)
        if shipment.to_mode == ADDRESS:
            missing.append(MISSING_DELIVERY)
        if shipment.packaging in MISSING_PACKAGING:
            missing.append(MISSING_PACKAGING[shipment.packaging])
        return Quote(
            carrier=self.name,
            total=float(int(price)),
            items=[PriceItem(f'Межтерминальная перевозка ({basis})', float(int(price)))],
            tariff='Авто, сборный груз',
            missing=missing,
        )
