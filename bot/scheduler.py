"""Итог дня ровно в 00:00 по Еревану (часовой пояс задаётся TZ_NAME).

Защита от дублей: кому уже отправлен отчёт за день, записывается в daily_sent,
поэтому повторная отправка после перезапуска дойдёт только до тех, кто его не получил.
"""
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
MAX_CATCHUP_DAYS = 7

# Пока идёт рассылка, плановая остановка бота ждёт её окончания.
send_lock = asyncio.Lock()


def next_midnight(now: datetime | None = None) -> datetime:
    now = now or datetime.now(TZ)
    return datetime.combine(now.date() + timedelta(days=1), time(0, 0), TZ)


async def send_daily(bot: Bot, db: DB, d: date) -> None:
    day = d.isoformat()
    async with send_lock:
        last = await db.get_setting(KEY)
        if last is not None and last >= day:
            return
        start, end = day_range(d)
        title = f"🌙 Итог дня {day_title(d)}"
        users = await db.all(
            "SELECT * FROM users WHERE tg_id IS NOT NULL AND nick IS NOT NULL AND approved=1")
        done = {r["tg_id"] for r in await db.all("SELECT tg_id FROM daily_sent WHERE day=?", day)}
        admin_text = await admin_report(db, start, end, title)
        jobs = []
        for u in users:
            if u["tg_id"] in done:
                continue
            text = admin_text if is_admin(u) else await worker_report(db, u, start, end, title)
            jobs.append((u["tg_id"], text))
        for chat_id, text in jobs:
            await send_safe(bot, chat_id, text)
            # отмечаем и при неудаче (бот заблокирован и т.п.), чтобы не слать повторно
            await db.run("INSERT OR IGNORE INTO daily_sent(day, tg_id) VALUES (?, ?)", day, chat_id)
            await asyncio.sleep(0.05)
        await db.set_setting(KEY, day)
        await db.run("DELETE FROM daily_sent WHERE day<?", (d - timedelta(days=MAX_CATCHUP_DAYS)).isoformat())
    log.info("Итог дня отправлен")


async def catch_up(bot: Bot, db: DB) -> None:
    yesterday = today() - timedelta(days=1)
    last = await db.get_setting(KEY)
    if last is None:
        await db.set_setting(KEY, yesterday.isoformat())  # первый запуск: старых отчётов не слать
        return
    d = max(date.fromisoformat(last) + timedelta(days=1), yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1))
    while d <= yesterday:
        # Отчёт пропущен (бот перезапускался в полночь или не работал) — досылаем.
        await send_daily(bot, db, d)
        d += timedelta(days=1)


async def daily_loop(bot: Bot, db: DB) -> None:
    try:
        await catch_up(bot, db)
    except Exception:
        log.exception("Ошибка досылки итога дня")

    while True:
        try:
            target = next_midnight()
            # спим частями, сверяясь с часами (защита от дрейфа)
            while (left := (target - datetime.now(TZ)).total_seconds()) > 0:
                await asyncio.sleep(min(left, 300))
            await send_daily(bot, db, target.date() - timedelta(days=1))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка отправки итога дня")
            await asyncio.sleep(30)
