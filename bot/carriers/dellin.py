import csv
import io
import time
from datetime import date

from .base import (
    ADDRESS, AVIA, MISSING_PACKAGING, PACKAGING_PALLET, PACKAGING_PROTECTIVE,
    BaseCarrier, CarrierError, CarrierNotConfigured, PriceItem, Quote, Shipment,
    normalize_city,
)

API = 'https://api.dellin.ru'
CACHE_TTL = 24 * 3600

PACKAGE_KEYWORDS = {
    PACKAGING_PROTECTIVE: ('жесткая упаковка', 'жесткий короб', 'обрешетка'),
    PACKAGING_PALLET: ('паллет', 'палет'),
}

PRICE_PARTS = (
    ('derival', 'Забор груза / приём на терминале'),
    ('intercity', 'Межтерминальная перевозка'),
    ('air', 'Авиаперевозка'),
    ('arrival', 'Доставка груза / выдача на терминале'),
    ('insurance', 'Страхование'),
    ('notify', 'Информирование'),
)


class DellinCarrier(BaseCarrier):
    """API: https://dev.dellin.ru/api/"""

    code = 'dellin'
    name = 'Деловые Линии'
    supports_avia = True
    secret_setting = 'DELLIN_APPKEY'

    _cities: dict[str, dict] = {}
    _cities_loaded_at: float = 0
    _packages: dict[str, str] = {}

    def is_configured(self) -> bool:
        return bool(self.secret)

    def _check(self):
        if not self.is_configured():
            raise CarrierNotConfigured('не задан appkey')

    async def _post(self, path: str, payload: dict) -> dict:
        async with self.client() as client:
            resp = await client.post(f'{API}{path}', json={'appkey': self.secret, **payload})
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or data.get('errors'):
            errors = data.get('errors') or []
            if isinstance(errors, dict):
                errors = [errors]
            message = '; '.join(str(e.get('detail') or e.get('title') or e) for e in errors)
            raise CarrierError(message or f'HTTP {resp.status_code}')
        return data

    async def _load_cities(self):
        self._check()
        if self._cities and time.time() - self._cities_loaded_at < CACHE_TTL:
            return
        meta = await self._post('/v3/public/terminals.json', {})
        async with self.client() as client:
            resp = await client.get(meta['url'])
            resp.raise_for_status()
            data = resp.json()
        cities = {}
        for city in data.get('city', []):
            cities.setdefault(normalize_city(city.get('name', '')), city)
        DellinCarrier._cities = cities
        DellinCarrier._cities_loaded_at = time.time()

    async def _city(self, name: str) -> dict:
        await self._load_cities()
        city = self._cities.get(normalize_city(name))
        if not city:
            raise CarrierError(f'нет терминалов в городе «{name}»')
        return city

    @staticmethod
    def _city_terminals(city: dict) -> list[dict]:
        terminals = city.get('terminals') or {}
        if isinstance(terminals, dict):
            terminals = terminals.get('terminal', [])
        return terminals

    async def _package_uid(self, packaging: str) -> str | None:
        if not self._packages:
            meta = await self._post('/v1/references/packages.json', {})
            async with self.client() as client:
                resp = await client.get(meta['url'])
                resp.raise_for_status()
            rows = csv.DictReader(io.StringIO(resp.content.decode('utf-8-sig')))
            DellinCarrier._packages = {
                normalize_city(row.get('name', '')): row.get('uid', '')
                for row in rows if row.get('uid')
            }
        for keyword in PACKAGE_KEYWORDS[packaging]:
            for name, uid in self._packages.items():
                if keyword in name:
                    return uid
        return None

    def _point(self, city: dict, mode: str, address: str, terminal_flag: str, produce_date: date | None) -> dict:
        point: dict = {}
        if produce_date:
            point['produceDate'] = produce_date.isoformat()
        if mode == ADDRESS:
            point['variant'] = 'address'
            point['address'] = {'search': f'{city.get("name", "")}, {address}'}
            point['time'] = {'worktimeStart': '09:00', 'worktimeEnd': '18:00'}
        else:
            terminals = self._city_terminals(city)
            suitable = [t for t in terminals if t.get(terminal_flag, True)] or terminals
            if not suitable:
                raise CarrierError(f'нет терминалов в городе «{city.get("name")}»')
            default = next((t for t in suitable if t.get('default')), suitable[0])
            point['variant'] = 'terminal'
            point['terminalID'] = str(default['id'])
        return point

    async def calculate(self, shipment: Shipment) -> Quote:
        from_city = await self._city(shipment.from_city)
        to_city = await self._city(shipment.to_city)

        delivery = {
            'deliveryType': {'type': 'avia' if shipment.delivery_type == AVIA else 'auto'},
            'derival': self._point(from_city, shipment.from_mode, shipment.from_address,
                                   'receiveCargo', shipment.ship_date),
            'arrival': self._point(to_city, shipment.to_mode, shipment.to_address, 'giveoutCargo', None),
        }
        if shipment.packaging in PACKAGE_KEYWORDS:
            package_uid = await self._package_uid(shipment.packaging)
            if package_uid:
                delivery['packages'] = [{'uid': package_uid, 'count': 1}]

        side = shipment.side_m
        payload = {
            'delivery': delivery,
            'cargo': {
                'quantity': 1,
                'length': side, 'width': side, 'height': side,
                'weight': shipment.weight,
                'totalVolume': shipment.volume,
                'totalWeight': shipment.weight,
                'hazardClass': 0,
            },
            'payment': {'type': 'cash', 'paymentCity': from_city.get('code')},
        }
        data = (await self._post('/v2/calculator.json', payload)).get('data', {})

        items: list[PriceItem] = []
        for key, title in PRICE_PARTS:
            part = data.get(key)
            price = part.get('price') if isinstance(part, dict) else part
            if isinstance(price, (int, float)) and price:
                items.append(PriceItem(title, float(price)))
        package_priced = False
        packages = data.get('packages')
        if isinstance(packages, dict):
            for package in packages.values():
                if isinstance(package, dict) and package.get('price'):
                    items.append(PriceItem(package.get('name', 'Упаковка'), float(package['price'])))
                    package_priced = True
        missing = []
        if shipment.packaging in MISSING_PACKAGING and not package_priced:
            missing.append(MISSING_PACKAGING[shipment.packaging])

        days = None
        dates = data.get('orderDates') or {}
        final = dates.get('arrivalToAddress') or dates.get('giveoutFromOspReceiver') or dates.get('arrivalToOspReceiver')
        if final:
            days = (date.fromisoformat(str(final)[:10]) - shipment.ship_date).days

        return Quote(
            carrier=self.name,
            total=float(data.get('price') or sum(i.price for i in items)),
            items=items,
            days_min=days,
            days_max=days,
            tariff='Авиа' if shipment.delivery_type == AVIA else 'Авто',
            missing=missing,
        )
