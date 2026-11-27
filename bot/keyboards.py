from aiogram.types import (
    CopyTextButton,
    DisabledButton,
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

# Цвета кнопок Telegram: зелёный — подтвердить/добавить, красный — удалить/отклонить,
# синий — главное действие экрана. Остальные (навигация) — обычные.
GREEN, RED, BLUE = "success", "danger", "primary"

# В главном меню выделены только самые частые действия.
_MENU_STYLE = {BTN_NEW_CLIENT: GREEN, BTN_RECEIPTS: BLUE}


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
        keyboard=[[KeyboardButton(text=t, style=_MENU_STYLE.get(t)) for t in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие в меню",
    )


def btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def ok_btn(text: str, data: str) -> InlineKeyboardButton:
    return btn(text, data, GREEN)


def danger_btn(text: str, data: str) -> InlineKeyboardButton:
    return btn(text, data, RED)


def main_btn(text: str, data: str) -> InlineKeyboardButton:
    return btn(text, data, BLUE)


def copy_btn(text: str, value: str) -> InlineKeyboardButton:
    """Кнопка, которая копирует значение в буфер обмена (до 256 символов)."""
    return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=str(value)[:256]))


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def label_btn(text: str) -> InlineKeyboardButton:
    """Неактивная кнопка-подпись (например, номер страницы)."""
    return InlineKeyboardButton(text=text, disabled=DisabledButton())


def back_btn(data: str, text: str = "« Назад") -> InlineKeyboardButton:
    return btn(text, data)


def pager(prefix: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    """Ряд «◀️ 2/5 ▶️». Пустой, если страница одна."""
    if pages <= 1:
        return []
    row = []
    row.append(btn("◀️", f"{prefix}{page - 1}") if page > 0 else label_btn(" "))
    row.append(label_btn(f"{page + 1} / {pages}"))
    row.append(btn("▶️", f"{prefix}{page + 1}") if page < pages - 1 else label_btn(" "))
    return row


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn("✖️ Отмена", "cancel")])


def confirm_kb(yes_data: str, no_data: str, yes_text: str = "🗑 Да, удалить") -> InlineKeyboardMarkup:
    return kb([danger_btn(yes_text, yes_data), btn("Отмена", no_data)])
