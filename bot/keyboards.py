from aiogram.types import (
    WebAppInfo,
    CopyTextButton,
    DisabledButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from .utils import is_admin

BTN_CLIENTS = "👥 Клиенты"
BTN_NEW_CLIENT = "➕ Новый клиент"
BTN_RECEIPTS = "🧾 Квитанции"
BTN_REQS = "💳 Реквизиты"
BTN_REPORTS = "📊 Отчёты"
BTN_STAFF = "👤 Команда"
BTN_LOG = "📜 Журнал"
BTN_MY_STATS = "📊 Моя статистика"

MENU_BUTTONS = frozenset({BTN_CLIENTS, BTN_NEW_CLIENT, BTN_RECEIPTS, BTN_REQS,
                          BTN_REPORTS, BTN_STAFF, BTN_LOG, BTN_MY_STATS,
                          "👤 Сотрудники"})  # старая подпись из прежней нижней клавиатуры

# Цвета кнопок Telegram: зелёный — подтвердить/добавить, красный — удалить/отклонить,
# синий — главное действие экрана. Остальные (навигация) — обычные.
GREEN, RED, BLUE = "success", "danger", "primary"

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


# Адрес мини-приложения (с параметром api=…); задаётся, когда туннель готов.
APP_URL: str | None = None


def app_btn(text: str = "📱 Открыть приложение") -> InlineKeyboardButton | None:
    if not APP_URL:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=APP_URL), style=BLUE)


def home_btn() -> InlineKeyboardButton:
    return btn("🏠 Меню", "m:home")


def menu_kb(user, pending: int = 0) -> InlineKeyboardMarkup:
    """Главное меню inline-кнопками. Счётчик квитанций подсвечивается, когда есть что проверять."""
    app = app_btn()
    if is_admin(user):
        receipts = f"🧾 Квитанции · {pending}" if pending else "🧾 Квитанции"
        return kb(
            [app] if app else [],
            [btn("👥 Клиенты", "m:clients"), ok_btn("➕ Новый клиент", "m:new")],
            [btn(receipts, "m:receipts", BLUE if pending else None), btn("💳 Реквизиты", "m:reqs")],
            [btn("📊 Отчёты", "m:reports"), btn("👤 Сотрудники", "m:staff")],
            [btn("📜 Журнал", "m:log")],
        )
    return kb(
        [app] if app else [],
        [btn("👥 Мои клиенты", "m:clients"), ok_btn("➕ Новый клиент", "m:new")],
        [btn("💳 Реквизиты", "m:reqs"), btn("📊 Моя статистика", "m:stats")],
    )
