from .base import (
    ADDRESS, AVIA, MISSING_PACKAGING, PACKAGING_PALLET, PACKAGING_PROTECTIVE, TERMINAL,
    BaseCarrier, CarrierError, CarrierNotConfigured, PriceItem, Quote, Shipment,
    normalize_city,
)

API = 'https://capi.tk-kit.com'

TYPE_STANDARD = '01'
TYPE_EXPRESS = '03'

PACKAGING_SERVICES = {
    PACKAGING_PROTECTIVE: 'T001',  # Жесткая доупаковка груза
    PACKAGING_PALLET: 'T002',      # Паллетирование (прозр. пленка)
}

PACKAGING_KEYWORDS = {
    PACKAGING_PROTECTIVE: ('упаков', 'обрешет'),
    PACKAGING_PALLET: ('паллет', 'палет'),
}


class KitCarrier(BaseCarrier):
    """КИТ.API: https://tk-kit.ru/services/api"""

    code = 'kit'
    name = 'ТК КИТ'
    supports_avia = True
    secret_setting = 'KIT_API_TOKEN'

    def is_configured(self) -> bool:
        return bool(self.secret)

    async def _post(self, path: str, payload: dict | None = None):
        if not self.is_configured():
            raise CarrierNotConfigured('не задан токен API')
        headers = {'Authorization': f'Bearer {self.secret}'}
        async with self.client(headers=headers) as client:
            resp = await client.post(f'{API}{path}', json=payload or {})
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            message = data.get('message') if isinstance(data, dict) else None
            raise CarrierError(message or f'HTTP {resp.status_code}')
        return data

    async def _city(self, name: str) -> dict:
        cities = await self._post('/1.1/tdd/search/by-name', {'title': name})
        if not cities:
            raise CarrierError(f'город «{name}» не обслуживается')
        wanted = normalize_city(name)
        exact = [c for c in cities if normalize_city(c.get('name', '')) == wanted]
        return (exact or cities)[0]

    async def _addresses(self, city_code: str) -> list[dict]:
        geo = await self._post('/1.0/geography/city/get-list', {'tdd_city_code': city_code})
        if not geo:
            return []
        return await self._post('/1.1/geography/address/get-list', {'geography_city_id': geo[0]['id']})

    async def calculate(self, shipment: Shipment) -> Quote:
        from_city = await self._city(shipment.from_city)
        to_city = await self._city(shipment.to_city)
        if shipment.from_mode == TERMINAL and from_city.get('required_pickup'):
            raise CarrierError(f'в г. {shipment.from_city} обязателен забор груза по адресу')
        if shipment.to_mode == TERMINAL and to_city.get('required_delivery'):
            raise CarrierError(f'в г. {shipment.to_city} обязательна доставка груза по адресу')

        transport_type = TYPE_EXPRESS if shipment.delivery_type == AVIA else TYPE_STANDARD
        side = shipment.side_cm
        payload = {
            'city_pickup_code': from_city['code'],
            'city_delivery_code': to_city['code'],
            'declared_price': 1000,
            'type': transport_type,
            'pick_up': 1 if shipment.from_mode == ADDRESS else 0,
            'delivery': 1 if shipment.to_mode == ADDRESS else 0,
            'places': [{
                'count_place': 1,
                'height': side, 'width': side, 'length': side,
                'weight': shipment.weight,
                'service': [PACKAGING_SERVICES[shipment.packaging]] if shipment.packaging in PACKAGING_SERVICES else [],
            }],
        }
        if shipment.from_mode == TERMINAL:
            addresses = await self._addresses(from_city['code'])
            if addresses:
                payload['dispatch_address_code'] = str(addresses[0]['address_code'])
        if shipment.to_mode == TERMINAL:
            addresses = await self._addresses(to_city['code'])
            if addresses:
                payload['pickpoint_address_code'] = str(addresses[0]['address_code'])

        data = await self._post('/2.0/order/calculate', payload)
        results = {}
        for chunk in data if isinstance(data, list) else [data]:
            if isinstance(chunk, dict):
                results.update(chunk)
        result = results.get(transport_type)
        if not result:
            kind = 'экспресс-доставка' if transport_type == TYPE_EXPRESS else 'стандартная доставка'
            raise CarrierError(f'{kind} по направлению не выполняется')

        details = [d for d in result.get('detail', []) if d.get('price')]
        items = [PriceItem(d.get('name', d.get('code', 'Услуга')), float(d['price'])) for d in details]

        missing = []
        if shipment.packaging in PACKAGING_SERVICES:
            code = PACKAGING_SERVICES[shipment.packaging]
            keywords = PACKAGING_KEYWORDS[shipment.packaging]
            priced = any(
                d.get('code') == code or any(k in normalize_city(str(d.get('name', ''))) for k in keywords)
                for d in details
            )
            if not priced:
                missing.append(MISSING_PACKAGING[shipment.packaging])

        days = result.get('time')
        return Quote(
            carrier=self.name,
            total=float(result.get('cost', 0)),
            items=items,
            days_min=days,
            days_max=days,
            tariff=result.get('name', ''),
            missing=missing,
        )
