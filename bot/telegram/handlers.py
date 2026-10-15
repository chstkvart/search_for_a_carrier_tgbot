import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..carriers.base import ADDRESS, AVIA, PACKAGING_TITLES, TERMINAL, Shipment
from ..services import calculate_all, save_request
from ..models import BotText
from ..texts import extra, label, t
from . import keyboards as kb
from .formatting import results_messages
from .states import Calc

logger = logging.getLogger(__name__)
router = Router()

MAX_WEIGHT_KG = 20000
MAX_VOLUME_M3 = 90


def parse_number(text: str, limit: float) -> float | None:
    try:
        value = float(text.strip().replace(',', '.').replace(' ', ''))
    except (ValueError, AttributeError):
        return None
    return value if 0 < value <= limit else None


def clean_city(text: str) -> str:
    city = ' '.join(text.strip().removeprefix('г.').strip().split())
    return city[:1].upper() + city[1:]


async def ask_delivery_type(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Calc.delivery_type)
    await message.answer(t('ask_delivery_type'), reply_markup=kb.delivery_type_kb())


@router.message(CommandStart())
@router.message(Command('new'))
async def start(message: Message, state: FSMContext):
    await message.answer(t('welcome'))
    for text in extra(BotText.PLACE_AFTER_WELCOME):
        await message.answer(text)
    await ask_delivery_type(message, state)


@router.callback_query(F.data == 'restart')
async def restart(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await ask_delivery_type(callback.message, state)


# --- 1. Вид доставки ---

@router.callback_query(Calc.delivery_type, F.data.startswith('type:'))
async def delivery_type_chosen(callback: CallbackQuery, state: FSMContext):
    delivery_type = callback.data.split(':', 1)[1]
    await state.update_data(delivery_type=delivery_type)
    chosen = label('btn_avia' if delivery_type == AVIA else 'btn_auto')
    await callback.message.edit_text(f'{t("ask_delivery_type")}\n<b>{escape(chosen)}</b>')
    await state.set_state(Calc.from_city)
    await callback.message.answer(t('ask_from_city'))
    await callback.answer()


# --- 2–3. Город и способ отправки ---

@router.message(Calc.from_city, F.text)
async def from_city_entered(message: Message, state: FSMContext):
    await state.update_data(from_city=clean_city(message.text))
    await state.set_state(Calc.from_mode)
    await message.answer(t('ask_from_mode'), reply_markup=kb.mode_kb(
        'from', label('btn_from_terminal'), label('btn_from_address'),
    ))


@router.callback_query(Calc.from_mode, F.data.in_({'from:t', 'from:a'}))
async def from_mode_chosen(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == 'from:t':
        await state.update_data(from_mode=TERMINAL, from_address='')
        await callback.message.edit_text(f'{t("ask_from_mode")}\n<b>{escape(label("btn_from_terminal"))}</b>')
        await state.set_state(Calc.to_city)
        await callback.message.answer(t('ask_to_city'))
    else:
        await state.update_data(from_mode=ADDRESS)
        await callback.message.edit_text(f'{t("ask_from_mode")}\n<b>{escape(label("btn_from_address"))}</b>')
        await state.set_state(Calc.from_address)
        await callback.message.answer(t('ask_from_address'))


@router.message(Calc.from_address, F.text)
async def from_address_entered(message: Message, state: FSMContext):
    await state.update_data(from_address=message.text.strip())
    await state.set_state(Calc.to_city)
    await message.answer(t('ask_to_city'))


# --- 4–5. Город и способ получения ---

@router.message(Calc.to_city, F.text)
async def to_city_entered(message: Message, state: FSMContext):
    await state.update_data(to_city=clean_city(message.text))
    await state.set_state(Calc.to_mode)
    await message.answer(t('ask_to_mode'), reply_markup=kb.mode_kb(
        'to', label('btn_to_terminal'), label('btn_to_address'),
    ))


@router.callback_query(Calc.to_mode, F.data.in_({'to:t', 'to:a'}))
async def to_mode_chosen(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == 'to:t':
        await state.update_data(to_mode=TERMINAL, to_address='')
        await callback.message.edit_text(f'{t("ask_to_mode")}\n<b>{escape(label("btn_to_terminal"))}</b>')
        await ask_packaging(callback.message, state)
    else:
        await state.update_data(to_mode=ADDRESS)
        await callback.message.edit_text(f'{t("ask_to_mode")}\n<b>{escape(label("btn_to_address"))}</b>')
        await state.set_state(Calc.to_address)
        await callback.message.answer(t('ask_to_address'))


@router.message(Calc.to_address, F.text)
async def to_address_entered(message: Message, state: FSMContext):
    await state.update_data(to_address=message.text.strip())
    await ask_packaging(message, state)


# --- 6. Упаковка ---

async def ask_packaging(message: Message, state: FSMContext):
    await state.set_state(Calc.packaging)
    await message.answer(t('ask_packaging'), reply_markup=kb.packaging_kb())


@router.callback_query(Calc.packaging, F.data.startswith('pack:'))
async def packaging_chosen(callback: CallbackQuery, state: FSMContext):
    packaging = callback.data.split(':', 1)[1]
    await callback.answer()
    if packaging not in PACKAGING_TITLES:
        return
    await state.update_data(packaging=packaging)
    await callback.message.edit_text(f'{t("ask_packaging")}\n<b>{escape(label(f"btn_pack_{packaging}"))}</b>')
    await state.set_state(Calc.weight)
    await callback.message.answer(t('ask_weight'))


# --- 7–8. Вес и объём ---

@router.message(Calc.weight, F.text)
async def weight_entered(message: Message, state: FSMContext):
    weight = parse_number(message.text, MAX_WEIGHT_KG)
    if weight is None:
        await message.answer(t('bad_weight', max=MAX_WEIGHT_KG))
        return
    await state.update_data(weight=weight)
    await state.set_state(Calc.volume)
    await message.answer(t('ask_volume'))


@router.message(Calc.volume, F.text)
async def volume_entered(message: Message, state: FSMContext):
    volume = parse_number(message.text, MAX_VOLUME_M3)
    if volume is None:
        await message.answer(t('bad_volume', max=MAX_VOLUME_M3))
        return
    data = await state.update_data(volume=volume)
    await state.clear()

    shipment = Shipment(
        delivery_type=data['delivery_type'],
        from_city=data['from_city'],
        from_mode=data['from_mode'],
        from_address=data.get('from_address', ''),
        to_city=data['to_city'],
        to_mode=data['to_mode'],
        to_address=data.get('to_address', ''),
        packaging=data['packaging'],
        weight=data['weight'],
        volume=volume,
    )
    wait = await message.answer(t('calculating'))
    result = await calculate_all(shipment)
    await wait.delete()

    messages = [
        *extra(BotText.PLACE_BEFORE_RESULTS),
        *results_messages(result),
        *extra(BotText.PLACE_AFTER_RESULTS),
    ]
    for i, text in enumerate(messages):
        await message.answer(text, reply_markup=kb.restart_kb() if i == len(messages) - 1 else None)

    try:
        await save_request(message.from_user, shipment, result)
    except Exception:
        logger.exception('Не удалось сохранить расчёт')


# --- Подсказки при неожиданном вводе ---

@router.message(Calc.delivery_type)
@router.message(Calc.from_mode)
@router.message(Calc.to_mode)
@router.message(Calc.packaging)
async def expect_button(message: Message):
    await message.answer(t('expect_button'))


@router.message()
async def fallback(message: Message):
    await message.answer(t('fallback'))
