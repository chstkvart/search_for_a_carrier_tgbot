from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..carriers.base import AUTO, AVIA, PACKAGING_NONE, PACKAGING_PALLET, PACKAGING_PROTECTIVE
from ..texts import label


def delivery_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label('btn_auto'), callback_data=f'type:{AUTO}'),
        InlineKeyboardButton(text=label('btn_avia'), callback_data=f'type:{AVIA}'),
    ]])


def mode_kb(prefix: str, terminal_label: str, address_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=terminal_label, callback_data=f'{prefix}:t')],
        [InlineKeyboardButton(text=address_label, callback_data=f'{prefix}:a')],
    ])


def packaging_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label('btn_pack_protective'), callback_data=f'pack:{PACKAGING_PROTECTIVE}')],
        [InlineKeyboardButton(text=label('btn_pack_pallet'), callback_data=f'pack:{PACKAGING_PALLET}')],
        [InlineKeyboardButton(text=label('btn_pack_none'), callback_data=f'pack:{PACKAGING_NONE}')],
    ])


def restart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label('btn_restart'), callback_data='restart'),
    ]])
