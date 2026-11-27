from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .utils import is_admin

BTN_CLIENTS = "👥 Клиенты"
BTN_NEW_CLIENT = "➕ Новый клиент"
BTN_RECEIPTS = "🧾 Квитанции"
BTN_REQS = "💳 Реквизиты"
BTN_REPORTS = "📊 Отчёты"
BTN_STAFF = "👤 Сотрудники"
BTN_LOG = "📜 Журнал"
BTN_MY_STATS = "📊 Моя статистика"

MENU_BUTTONS = frozenset({BTN_CLIENTS, BTN_NEW_CLIENT, BTN_RECEIPTS, BTN_REQS,
                          BTN_REPORTS, BTN_STAFF, BTN_LOG, BTN_MY_STATS})


def main_kb(user) -> ReplyKeyboardMarkup:
    if is_admin(user):
        rows = [
            [BTN_CLIENTS, BTN_NEW_CLIENT],
            [BTN_RECEIPTS, BTN_REQS],
            [BTN_REPORTS, BTN_STAFF],
            [BTN_LOG],
        ]
    else:
        rows = [
            [BTN_CLIENTS, BTN_NEW_CLIENT],
            [BTN_REQS, BTN_MY_STATS],
        ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
    )


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn("✖️ Отмена", "cancel")])
