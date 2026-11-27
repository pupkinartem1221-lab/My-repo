"""Итог дня ровно в 00:00 по Еревану (часовой пояс задаётся TZ_NAME)."""
import asyncio
import logging
from datetime import date, datetime, time, timedelta

from aiogram import Bot

from .db import DB
from .notify import send_safe
from .reports import admin_report, day_title, worker_report
from .utils import TZ, day_range, is_admin, today

log = logging.getLogger(__name__)
KEY = "last_daily_report"


async def send_daily(bot: Bot, db: DB, d: date) -> None:
    if await db.get_setting(KEY) == d.isoformat():
        return
    start, end = day_range(d)
    title = f"🌙 Итог дня {day_title(d)}"
    users = await db.all("SELECT * FROM users WHERE tg_id IS NOT NULL AND nick IS NOT NULL")
    admin_text = await admin_report(db, start, end, title)
    for u in users:
        text = admin_text if is_admin(u) else await worker_report(db, u, start, end, title)
        await send_safe(bot, u["tg_id"], text)
        await asyncio.sleep(0.05)
    await db.set_setting(KEY, d.isoformat())
    log.info("Daily report sent")


async def daily_loop(bot: Bot, db: DB) -> None:
    yesterday = today() - timedelta(days=1)
    last = await db.get_setting(KEY)
    if last is None:
        await db.set_setting(KEY, yesterday.isoformat())  # первый запуск: не слать старых отчётов
    elif last < yesterday.isoformat():
        # Отчёт пропущен (бот перезапускался ровно в полночь) — досылаем.
        await send_daily(bot, db, yesterday)

    while True:
        now = datetime.now(TZ)
        nxt = datetime.combine(now.date() + timedelta(days=1), time(0, 0), TZ)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        # дождаться, пока полночь точно наступит
        while datetime.now(TZ) < nxt:
            await asyncio.sleep(0.2)
        try:
            await send_daily(bot, db, nxt.date() - timedelta(days=1))
        except Exception:
            log.exception("Daily report failed")
