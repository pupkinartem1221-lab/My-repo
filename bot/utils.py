import html
import os
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Yerevan"))

CLIENT_STATUSES = {
    "work": "🔄 В работе",
    "paid": "✅ Оплачено",
    "lost": "❌ Слив",
}
PAYMENT_STATUSES = {
    "pending": "⏳ Ожидает подтверждения",
    "confirmed": "✅ Подтверждена",
    "rejected": "❌ Отклонена",
}
ROLES = {"owner": "👑 Главный админ", "admin": "🛡 Админ", "worker": "👷 Сотрудник"}


def now() -> int:
    return int(time.time())


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def is_admin(user) -> bool:
    return user["role"] in ("owner", "admin")


def fmt_dt(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def fmt_money(kop: int | float | None) -> str:
    kop = int(round(kop or 0))
    sign = "-" if kop < 0 else ""
    hr, k = divmod(abs(kop), 100)
    s = f"{hr:,}".replace(",", " ")
    if k:
        s += f",{k:02d}"
    return f"{sign}{s} ₴"


def parse_money(text: str) -> int | None:
    t = (text or "").replace(" ", "").replace(" ", "").replace("₴", "")
    t = t.replace("грн", "").replace(",", ".")
    try:
        value = Decimal(t)
    except InvalidOperation:
        return None
    if value <= 0 or value > Decimal("1000000000"):
        return None
    return int((value * 100).quantize(Decimal("1")))


def user_name(row) -> str:
    if row is None:
        return "—"
    if row["nick"]:
        return esc(row["nick"])
    if row["username"]:
        return "@" + esc(row["username"])
    return f"id{row['id']}"


def day_range(d: date) -> tuple[int, int]:
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def today() -> date:
    return datetime.now(TZ).date()
