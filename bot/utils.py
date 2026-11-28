import html
import os
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Yerevan"))

CLIENT_STATUSES = {
    "work": "🔄 В работе",
    "paid": "✅ Оплачено",
    "lost": "❌ Слив",
}
PAYMENT_STATUSES = {
    "pending": "⏳ На проверке",
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


def plural(n: int, one: str, few: str, many: str) -> str:
    n = int(n or 0)
    m, mm = n % 10, n % 100
    word = one if m == 1 and mm != 11 else few if 2 <= m <= 4 and not 12 <= mm <= 14 else many
    return f"{n} {word}"


def pays(n: int) -> str:
    return plural(n, "оплата", "оплаты", "оплат")


def fmt_short(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m %H:%M")


def fmt_money(kop: int | float | None) -> str:
    kop = int(round(kop or 0))
    sign = "-" if kop < 0 else ""
    hr, k = divmod(abs(kop), 100)
    s = f"{hr:,}".replace(",", " ")
    if k:
        s += f",{k:02d}"
    return f"{sign}{s} ₴"


def parse_money(text: str) -> int | None:
    """Сумма в гривнах → копейки. Только цифры и максимум 2 знака после запятой."""
    t = (text or "").strip().lower()
    for junk in (" ", "\u00a0", "\u202f", "\u2009", "\t", "₴", "грн", "uah"):
        t = t.replace(junk, "")
    t = t.rstrip(".").replace(",", ".")
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", t, flags=re.ASCII):
        return None
    kop = int(Decimal(t) * 100)
    return kop if 0 < kop <= 100_000_000 * 100 else None


def clip(value, limit: int) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def fit(lines: list[str], limit: int = 4000, tail: str = "…") -> str:
    """Склеить строки, не превышая лимит и не разрывая HTML-теги посреди строки."""
    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > limit - len(tail) - 1:
            out.append(tail)
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def user_label(row) -> str:
    """Имя для кнопок (обычный текст, без HTML)."""
    if row is None:
        return "—"
    if row["nick"]:
        return row["nick"]
    if row["username"]:
        return "@" + row["username"]
    return f"id{row['id']}"


def phone_intl(phone: str | None) -> str | None:
    """Номер в международном формате без «+» (для ссылок на мессенджеры). Без кода — считаем украинским."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 10 and d.startswith("0"):
        d = "38" + d
    elif len(d) == 9:
        d = "380" + d
    return d if 10 <= len(d) <= 15 else None


def messenger_links(phone: str | None) -> dict[str, str]:
    d = phone_intl(phone)
    if not d:
        return {}
    return {
        "whatsapp": f"https://wa.me/{d}",
        "telegram": f"https://t.me/+{d}",
    }


def deleted_req_label(label: str | None) -> str:
    """«UA…IBAN (ФИО)» из снимка в оплате → «…123456 ФИО (удалён)»."""
    if not label:
        return "без реквизита"
    m = re.match(r"\s*([A-Z]{2}\d{2}[A-Z0-9]+)\s*(?:\((.*)\))?\s*$", label)
    if not m:
        return f"{label} (удалён)"
    holder = f" {m.group(2)}" if m.group(2) else ""
    return f"…{m.group(1)[-6:]}{holder} (удалён)"


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def iban_ok(iban: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    if iban.startswith("UA") and len(iban) != 29:
        return False
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def ipn_checksum_ok(ipn: str) -> bool:
    """Контрольная цифра РНОКПП (ІПН). При несовпадении только предупреждаем."""
    d = [int(c) for c in ipn]
    weights = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
    return sum(a * b for a, b in zip(d, weights)) % 11 % 10 == d[9]


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
