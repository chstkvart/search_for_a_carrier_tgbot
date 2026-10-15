import asyncio
from functools import cached_property

from django.conf import settings

from .base import (
    AVIA, MISSING_PACKAGING, TERMINAL,
    BaseCarrier, CarrierError, CarrierNotConfigured, PriceItem, Quote, Shipment,
)

# Экспресс-тарифы DPD идут авиатранспортом, остальные — наземным.
AVIA_SERVICES = {'NDY', 'BZP', 'CSM'}


class DpdCarrier(BaseCarrier):
    """SOAP API: https://www.dpd.ru/ru/integration"""

    code = 'dpd'
    name = 'DPD'
    supports_avia = True
    login_setting = 'DPD_CLIENT_NUMBER'
    secret_setting = 'DPD_CLIENT_KEY'

    def is_configured(self) -> bool:
        return bool(self.login and self.secret)

    @property
    def _auth(self) -> dict:
        if not self.is_configured():
            raise CarrierNotConfigured('не заданы номер клиента / ключ')
        if not self.login.strip().isdigit():
            raise CarrierError('номер клиента DPD должен состоять из цифр')
        return {'clientNumber': int(self.login), 'clientKey': self.secret}

    def _soap(self, service: str):
        from zeep import Client, Settings
        from zeep.transports import Transport

        transport = Transport(timeout=settings.CARRIER_HTTP_TIMEOUT, operation_timeout=settings.CARRIER_HTTP_TIMEOUT)
        return Client(f'{settings.DPD_API_URL.rstrip("/")}/{service}?wsdl',
                      transport=transport, settings=Settings(strict=False))

    @cached_property
    def _calculator(self):
        return self._soap('calculator2')

    def _calculate_sync(self, shipment: Shipment) -> list:
        from zeep.exceptions import Fault

        request = {
            'auth': self._auth,
            'pickup': {'cityName': shipment.from_city, 'countryCode': 'RU'},
            'delivery': {'cityName': shipment.to_city, 'countryCode': 'RU'},
            'selfPickup': shipment.from_mode == TERMINAL,
            'selfDelivery': shipment.to_mode == TERMINAL,
            'weight': shipment.weight,
            'volume': shipment.volume,
            'pickupDate': shipment.ship_date,
        }
        try:
            return self._calculator.service.getServiceCost2(request=request) or []
        except Fault as exc:
            raise CarrierError(str(exc.message)) from exc

    async def calculate(self, shipment: Shipment) -> Quote:
        services = await asyncio.to_thread(self._calculate_sync, shipment)
        is_avia = shipment.delivery_type == AVIA
        suitable = [s for s in services if (s['serviceCode'] in AVIA_SERVICES) == is_avia]
        if not suitable:
            raise CarrierError('нет подходящего тарифа по направлению')
        best = min(suitable, key=lambda s: float(s['cost']))

        missing = [MISSING_PACKAGING[shipment.packaging]] if shipment.packaging in MISSING_PACKAGING else []
        cost = float(best['cost'])
        return Quote(
            carrier=self.name,
            total=cost,
            items=[PriceItem(f'Перевозка ({best["serviceName"]})', cost)],
            days_min=best['days'],
            days_max=best['days'],
            tariff=best['serviceName'],
            missing=missing,
        )
