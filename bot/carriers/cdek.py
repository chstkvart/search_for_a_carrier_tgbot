import time

from django.conf import settings

from .base import (
    ADDRESS, AVIA, MISSING_PACKAGING, PACKAGING_PALLET, PACKAGING_PROTECTIVE, TERMINAL,
    BaseCarrier, CarrierError, CarrierNotConfigured, PriceItem, Quote, Shipment,
    normalize_city,
)

# delivery_mode в ответе tarifflist
DELIVERY_MODES = {
    (ADDRESS, ADDRESS): 1,
    (ADDRESS, TERMINAL): 2,
    (TERMINAL, ADDRESS): 3,
    (TERMINAL, TERMINAL): 4,
}

SERVICE_NAMES = {
    'INSURANCE': 'Страхование',
    'BUBBLE_WRAP': 'Воздушно-пузырчатая плёнка',
    'WASTE_PAPER': 'Макулатурная бумага',
    'TAKE_SENDER': 'Забор у отправителя',
    'DELIV_RECEIVER': 'Доставка получателю',
    'HEAVY_CARGO': 'Надбавка за тяжёлый груз',
    'LARGE_CARGO': 'Надбавка за крупногабаритный груз',
    'PART_DELIV': 'Частичная доставка',
}


class CdekCarrier(BaseCarrier):
    """API v2: https://api-docs.cdek.ru"""

    code = 'cdek'
    name = 'СДЭК'
    supports_avia = True
    login_setting = 'CDEK_CLIENT_ID'
    secret_setting = 'CDEK_CLIENT_SECRET'

    _token: str = ''
    _token_expires: float = 0
    _token_owner: tuple[str, str] = ('', '')

    @property
    def base_url(self) -> str:
        return settings.CDEK_API_URL.rstrip('/')

    @property
    def is_test(self) -> bool:
        return 'api.edu.cdek.ru' in self.base_url

    def is_configured(self) -> bool:
        return bool(self.login and self.secret)

    async def _auth_headers(self) -> dict:
        if not self.is_configured():
            raise CarrierNotConfigured('не заданы Client ID / Client Secret')
        owner = (self.login, self.secret)
        if not self._token or time.time() > self._token_expires or owner != self._token_owner:
            async with self.client() as client:
                resp = await client.post(f'{self.base_url}/oauth/token', data={
                    'grant_type': 'client_credentials',
                    'client_id': self.login,
                    'client_secret': self.secret,
                })
                if resp.status_code in (400, 401):
                    raise CarrierError('неверные Client ID / Client Secret')
                resp.raise_for_status()
                data = resp.json()
            CdekCarrier._token = data['access_token']
            CdekCarrier._token_expires = time.time() + int(data.get('expires_in', 3600)) - 60
            CdekCarrier._token_owner = owner
        return {'Authorization': f'Bearer {self._token}'}

    async def _request(self, method: str, path: str, **kwargs):
        headers = await self._auth_headers()
        async with self.client(headers=headers) as client:
            resp = await client.request(method, f'{self.base_url}{path}', **kwargs)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or (isinstance(data, dict) and data.get('errors')):
            errors = data.get('errors') if isinstance(data, dict) else None
            message = '; '.join(e.get('message', '') for e in errors) if errors else resp.text[:200]
            raise CarrierError(message)
        return data

    async def _city_code(self, city: str) -> int:
        cities = await self._request('GET', '/location/cities', params={
            'city': city, 'country_codes': 'RU', 'size': 10,
        })
        if not cities:
            raise CarrierError(f'город «{city}» не найден')
        wanted = normalize_city(city)
        exact = [c for c in cities if normalize_city(c.get('city', '')) == wanted]
        return (exact or cities)[0]['code']

    async def calculate(self, shipment: Shipment) -> Quote:
        from_code = await self._city_code(shipment.from_city)
        to_code = await self._city_code(shipment.to_city)

        from_location = {'code': from_code}
        if shipment.from_mode == ADDRESS and shipment.from_address:
            from_location['address'] = shipment.from_address
        to_location = {'code': to_code}
        if shipment.to_mode == ADDRESS and shipment.to_address:
            to_location['address'] = shipment.to_address

        side = shipment.side_cm
        packages = [{
            'weight': int(shipment.weight * 1000),
            'length': side, 'width': side, 'height': side,
        }]
        base = {'from_location': from_location, 'to_location': to_location, 'packages': packages}

        tariffs = (await self._request('POST', '/calculator/tarifflist', json=base)).get('tariff_codes', [])
        mode = DELIVERY_MODES[(shipment.from_mode, shipment.to_mode)]
        is_avia = shipment.delivery_type == AVIA

        def is_express(t: dict) -> bool:
            name = t.get('tariff_name', '').lower()
            return 'экспресс' in name and 'магистраль' not in name

        suitable = [
            t for t in tariffs
            if t.get('delivery_mode') == mode and is_express(t) == is_avia
        ]
        if not suitable:
            raise CarrierError('нет подходящего тарифа по направлению')
        best = min(suitable, key=lambda t: t['delivery_sum'])

        note = ''
        missing = []
        services = []
        if shipment.packaging == PACKAGING_PROTECTIVE:
            services.append({'code': 'BUBBLE_WRAP', 'parameter': str(max(1, round(side * 6 / 100)))})
        elif shipment.packaging == PACKAGING_PALLET:
            missing.append(MISSING_PACKAGING[PACKAGING_PALLET])

        payload = {**base, 'tariff_code': best['tariff_code']}
        try:
            detail = await self._request('POST', '/calculator/tariff', json={**payload, 'services': services})
        except CarrierError:
            detail = await self._request('POST', '/calculator/tariff', json=payload)
            if services:
                missing.append(MISSING_PACKAGING[PACKAGING_PROTECTIVE])

        service_items = []
        for service in detail.get('services', []):
            price = float(service.get('total_sum', service.get('sum', 0)))
            if price:
                service_items.append(PriceItem(SERVICE_NAMES.get(service.get('code'), service.get('code', 'Услуга')), price))
        # delivery_sum приходит без НДС, total_sum — с НДС
        total = float(detail.get('total_sum') or 0)
        delivery = total - sum(i.price for i in service_items) if total else float(detail.get('delivery_sum', 0))
        items = [PriceItem(f'Перевозка ({best["tariff_name"]}), с НДС', round(delivery, 2)), *service_items]

        days_min = detail.get('period_min', best.get('period_min'))
        days_max = detail.get('period_max', best.get('period_max'))
        if self.is_test:
            # Тестовый контур на любой маршрут отвечает сроком 0–1 день.
            days_min = days_max = None
            note = ' '.join(filter(None, [note, 'Тестовый контур СДЭК: цена и срок условные, '
                                                'для реальных данных нужны боевые ключи.']))

        return Quote(
            carrier=self.name,
            total=total or sum(i.price for i in items),
            items=items,
            days_min=days_min,
            days_max=days_max,
            tariff=best['tariff_name'],
            note=note,
            missing=missing,
        )
