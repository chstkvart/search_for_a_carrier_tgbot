import re
import time

from .base import (
    ADDRESS, AUTO, AVIA, MISSING_DELIVERY, MISSING_PACKAGING, MISSING_PICKUP, PACKAGING_PALLET, PACKAGING_PROTECTIVE,
    BaseCarrier, CarrierError, PriceItem, Quote, Shipment, normalize_city, parse_days,
)

TOWNS_URL = 'https://pecom.ru/ru/calc/towns.php'
CALC_URL = 'https://calc.pecom.ru/bitrix/components/pecom/calc/ajax.php'
TOWNS_TTL = 24 * 3600


class PecomCarrier(BaseCarrier):
    """Публичный калькулятор ПЭК: https://pecom.ru/business/developers/api_public/"""

    code = 'pecom'
    name = 'ПЭК'
    supports_avia = True

    _towns: dict[str, list[int]] = {}
    _towns_loaded_at: float = 0

    async def _load_towns(self):
        if self._towns and time.time() - self._towns_loaded_at < TOWNS_TTL:
            return
        async with self.client() as client:
            resp = await client.get(TOWNS_URL)
            resp.raise_for_status()
            data = resp.json()
        towns: dict[str, list[int]] = {}
        for cities in data.values():
            for town_id, title in cities.items():
                key = normalize_city(re.sub(r'\s*\(.*\)$', '', title))
                towns.setdefault(key, []).append(int(town_id))
        # Отрицательный ID — основной филиал города, его ставим первым.
        for ids in towns.values():
            ids.sort(key=lambda i: (i > 0, abs(i)))
        PecomCarrier._towns = towns
        PecomCarrier._towns_loaded_at = time.time()

    async def _town_id(self, city: str) -> int:
        await self._load_towns()
        ids = self._towns.get(normalize_city(city))
        if not ids:
            raise CarrierError(f'город «{city}» не обслуживается')
        return ids[0]

    async def calculate(self, shipment: Shipment) -> Quote:
        take_id = await self._town_id(shipment.from_city)
        deliver_id = await self._town_id(shipment.to_city)

        side = shipment.side_m
        protective = 1 if shipment.packaging == PACKAGING_PROTECTIVE else 0
        params = [
            ('places[0][]', side), ('places[0][]', side), ('places[0][]', side),
            ('places[0][]', shipment.volume), ('places[0][]', shipment.weight),
            ('places[0][]', 0), ('places[0][]', protective),
            ('take[town]', take_id),
            ('deliver[town]', deliver_id),
            ('pal', shipment.pallets_count if shipment.packaging == PACKAGING_PALLET else 0),
        ]
        async with self.client() as client:
            resp = await client.get(CALC_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get('error'):
            raise CarrierError('; '.join(map(str, data['error'])))

        transport_key = AVIA if shipment.delivery_type == AVIA else AUTO
        if transport_key not in data:
            kind = 'авиаперевозка' if transport_key == AVIA else 'автоперевозка'
            raise CarrierError(f'{kind} по направлению не выполняется')

        items: list[PriceItem] = []

        def add(key: str, title: str | None = None) -> bool:
            value = data.get(key)
            if isinstance(value, list) and len(value) >= 3 and value[2]:
                items.append(PriceItem(title or value[0], float(value[2])))
                return True
            if isinstance(value, dict) and value.get('3'):
                items.append(PriceItem(title or value.get('1') or key, float(value['3'])))
                return True
            return False

        missing = []
        if shipment.from_mode == ADDRESS and not add('take', 'Забор груза по адресу'):
            missing.append(MISSING_PICKUP)
        add(transport_key, 'Межтерминальная перевозка' if transport_key == AUTO else 'Авиаперевозка')
        if transport_key == AUTO:
            add('alma_auto', 'Перевозка Екатеринбург – Алматы')
        if shipment.to_mode == ADDRESS and not add('deliver', 'Доставка груза по адресу'):
            missing.append(MISSING_DELIVERY)
        protective_priced = add('ADD', 'Защитная транспортировочная упаковка' if protective else None)
        add('ADD_1')
        pallet_priced = add('ADD_2', 'Палетирование')
        add('ADD_3', 'Страхование')
        add('ADD_4')

        if (shipment.packaging == PACKAGING_PROTECTIVE and not protective_priced
                or shipment.packaging == PACKAGING_PALLET and not pallet_priced):
            missing.append(MISSING_PACKAGING[shipment.packaging])
        note = ''

        days_min, days_max = parse_days(data.get('periods_days') if transport_key == AUTO
                                        else re.sub(r'<[^>]+>', ' ', data.get('aperiods', '')))
        return Quote(
            carrier=self.name,
            total=round(sum(i.price for i in items), 2),
            items=items,
            days_min=days_min,
            days_max=days_max,
            tariff='Авиа' if transport_key == AVIA else 'Авто',
            note=note,
            missing=missing,
        )
