from .base import BaseCarrier, CarrierError, Quote, Shipment


class ManualQuoteCarrier(BaseCarrier):
    """ТК без онлайн-расчёта: калькулятор на сайте только отправляет заявку менеджеру."""

    default_contacts: str = ''

    async def calculate(self, shipment: Shipment) -> Quote:
        contacts = self.contacts or self.default_contacts
        if not contacts:
            raise CarrierError('онлайн-расчёта нет, стоимость считает менеджер')
        raise CarrierError(f'онлайн-расчёта нет, стоимость считает менеджер: {contacts}')


class CustomCarrier(ManualQuoteCarrier):
    """ТК, добавленная заказчиком в админке."""

    def __init__(self, config_id: int, name: str):
        self.code = f'custom-{config_id}'
        self.name = name
        super().__init__()


class MagistralCarrier(ManualQuoteCarrier):
    code = 'magistral'
    name = 'Магистраль'
    default_contacts = 'заявка через сайт переезд-в-другой-город.рф'


class BuroCarrier(ManualQuoteCarrier):
    code = 'buro'
    name = 'Бюро перевозок'
    default_contacts = '8 (800) 600-28-42, byuro-perevozok.ru'
