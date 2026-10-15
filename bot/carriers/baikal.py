import re

from django.conf import settings

from .base import (
    ADDRESS, MISSING_PACKAGING, PACKAGING_PALLET, PACKAGING_PROTECTIVE,
    BaseCarrier, CarrierError, CarrierNotConfigured, PriceItem, Quote, Shipment,
    normalize_city,
)

SERVICE_KEYWORDS = {
    PACKAGING_PROTECTIVE: ('обрешет', 'жесткая упаковка'),
    PACKAGING_PALLET: ('паллет', 'палет'),
}

STREET_PREFIXES = re.compile(
    r'^(ул|улица|пр-кт|проспект|пр|пер|переулок|ш|шоссе|б-р|бульвар|наб|набережная|пл|площадь|проезд|мкр)\.?\s+',
    re.IGNORECASE,
)


class BaikalCarrier(BaseCarrier):
    """REST API v2: https://www.baikalsr.ru/dev/api/"""

    code = 'baikal'
    name = 'Байкал Сервис'
    supports_avia = False
    secret_setting = 'BAIKAL_API_KEY'

    @property
    def base_url(self) -> str:
        return settings.BAIKAL_API_URL.rstrip('/')

    def is_configured(self) -> bool:
        return bool(self.secret)

    async def _request(self, method: str, path: str, **kwargs):
        if not self.is_configured():
            raise CarrierNotConfigured('не задан API-ключ')
        async with self.client(auth=(self.secret, '')) as client:
            resp = await client.request(method, f'{self.base_url}{path}', **kwargs)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise CarrierError(f'HTTP {resp.status_code}: {resp.text[:200]}')
        if isinstance(data, dict) and data.get('errors'):
            raise CarrierError('; '.join(str(e.get('description', e)) for e in data['errors']))
        return data

    async def _city_guid(self, name: str) -> str:
        cities = await self._request('GET', '/v2/fias/cities', params={'text': name})
        if not cities:
            raise CarrierError(f'город «{name}» не найден')
        wanted = normalize_city(name)
        exact = [c for c in cities if normalize_city(c.get('name', '')) == wanted]
        # type 3 — город, в котором есть филиал
        exact.sort(key=lambda c: str(c.get('type')) != '3')
        return (exact or cities)[0]['guid']

    async def _address_point(self, city_guid: str, address: str) -> dict:
        parts = [p.strip() for p in address.split(',') if p.strip()]
        house = ''
        if parts and re.search(r'\d', parts[-1]):
            house = re.sub(r'^(д|дом)\.?\s*', '', parts.pop(), flags=re.IGNORECASE)
        street_text = STREET_PREFIXES.sub('', parts[-1] if parts else address)
        streets = await self._request('GET', '/v2/fias/streets', params={'guid': city_guid, 'text': street_text})
        if not streets:
            raise CarrierError(f'улица «{street_text}» не найдена в справочнике ФИАС')
        return {
            'Street': streets[0]['guid'],
            'House': house,
            'Housing': '',
            'Building': '',
            'TimeFrom': '09:00',
            'TimeTo': '18:00',
        }

    async def _service_id(self, city_guid: str, packaging: str) -> int | None:
        services = await self._request('GET', f'/v2/directory/services/{city_guid}')
        for keyword in SERVICE_KEYWORDS[packaging]:
            for service in services or []:
                if keyword in normalize_city(service.get('serviceName', '')):
                    return service.get('serviceId')
        return None

    async def calculate(self, shipment: Shipment) -> Quote:
        from_guid = await self._city_guid(shipment.from_city)
        to_guid = await self._city_guid(shipment.to_city)

        departure: dict = {'CityGuid': from_guid}
        if shipment.from_mode == ADDRESS:
            departure['PickUp'] = {
                **await self._address_point(from_guid, shipment.from_address),
                'Date': f'{shipment.ship_date.isoformat()}T00:00:00',
            }
        destination: dict = {'CityGuid': to_guid}
        if shipment.to_mode == ADDRESS:
            destination['Delivery'] = await self._address_point(to_guid, shipment.to_address)

        missing = []
        services = []
        if shipment.packaging in SERVICE_KEYWORDS:
            service_id = await self._service_id(from_guid, shipment.packaging)
            if service_id:
                services.append(service_id)
            else:
                missing.append(MISSING_PACKAGING[shipment.packaging])

        side = shipment.side_m
        payload = {
            'Departure': departure,
            'Destination': destination,
            'Cargo': {'SummaryCargo': {
                'Length': side, 'Width': side, 'Height': side,
                'Volume': shipment.volume,
                'Weight': shipment.weight,
                'Units': 1,
                'Oversized': 0,
                'EstimatedCost': 1000,
                'Services': services,
            }},
        }
        data = await self._request('POST', '/v2/calculator', json=payload)

        items = [
            PriceItem(s.get('name', 'Услуга'), float(s['cost']))
            for section in ('departure', 'cargo', 'destination')
            for s in (data.get(section) or {}).get('services', [])
            if s.get('cost')
        ]
        days = (data.get('transit') or {}).get('int')
        return Quote(
            carrier=self.name,
            total=float(data.get('total') or sum(i.price for i in items)),
            items=items,
            days_min=days,
            days_max=days,
            tariff='Авто',
            missing=missing,
        )
