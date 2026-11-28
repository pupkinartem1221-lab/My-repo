"""Общие правила для бота и мини-приложения."""
from .db import DB

RECEIPT_REQUIRED = "Чтобы поставить «Оплачено», прикрепите квитанцию"


async def has_receipt(db: DB, client_id: int) -> bool:
    """Есть ли у клиента квитанция на проверке или подтверждённая."""
    return await db.one("SELECT 1 FROM payments WHERE client_id=? AND status IN ('pending','confirmed') LIMIT 1",
                        client_id) is not None


async def revert_paid_if_no_receipt(db: DB, client_id: int | None) -> bool:
    """«Оплачено» без квитанции не остаётся: вернуть клиента в работу. True — статус изменён."""
    if not client_id:
        return False
    cur = await db.run(
        "UPDATE clients SET status='work' WHERE id=? AND status='paid' AND NOT EXISTS "
        "(SELECT 1 FROM payments WHERE client_id=? AND status IN ('pending','confirmed'))", client_id, client_id)
    return cur.rowcount > 0
