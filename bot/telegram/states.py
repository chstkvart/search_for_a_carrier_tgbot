from aiogram.fsm.state import State, StatesGroup


class Calc(StatesGroup):
    delivery_type = State()
    from_city = State()
    from_mode = State()
    from_address = State()
    to_city = State()
    to_mode = State()
    to_address = State()
    packaging = State()
    weight = State()
    volume = State()
