import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_config
from .db import DB
from .fsm_storage import SQLiteStorage
from .handlers import clients, common, fallback, payments, reports, requisites, staff
from .middleware import AccessMiddleware
from .scheduler import daily_loop
from .storage_sync import DataSync
from .utils import now

log = logging.getLogger("crm")


class Persister:
    def __init__(self, db: DB, sync: DataSync):
        self.db = db
        self.sync = sync
        self.lock = asyncio.Lock()

    async def save(self) -> None:
        if not self.sync.enabled:
            return
        async with self.lock:
            if not self.db.dirty:
                return
            self.db.dirty = False
            snap = self.db.path + ".snap"
            try:
                await self.db.snapshot(snap)
                await asyncio.to_thread(self.sync.save, snap)
            except Exception as e:
                self.db.dirty = True
                log.error("Не удалось сохранить базу: %s", e)

    async def loop(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.save()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    cfg = load_config()
    sync = DataSync(cfg.data_repo, cfg.gh_token, cfg.data_branch, cfg.db_password)
    await asyncio.to_thread(sync.load, cfg.db_path)

    db = DB(cfg.db_path)
    await db.connect()
    try:
        await run_bot(cfg, db, Persister(db, sync))
    finally:
        await db.close()
        log.info("Остановлен")


async def run_bot(cfg, db: DB, persister: Persister) -> None:
    # главный админ всегда есть в базе
    await db.run("UPDATE users SET role='admin' WHERE role='owner' AND (tg_id IS NULL OR tg_id<>?)", cfg.owner_id)
    await db.run(
        "INSERT INTO users(tg_id, role, percent, created_at) VALUES (?, 'owner', 50, ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET role='owner'", cfg.owner_id, now())

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                       link_preview_is_disabled=True))
    dp = Dispatcher(storage=SQLiteStorage(db))
    dp["db"] = db
    dp["cfg"] = cfg
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    dp.include_routers(common.router, clients.router, payments.router, requisites.router,
                       staff.router, reports.router, fallback.router)

    tasks = [
        asyncio.create_task(persister.loop(cfg.save_interval)),
        asyncio.create_task(daily_loop(bot, db)),
    ]
    if cfg.run_seconds > 0:
        async def stop_later():
            await asyncio.sleep(cfg.run_seconds)
            log.info("Плановая остановка")
            await dp.stop_polling()
        tasks.append(asyncio.create_task(stop_later()))

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: None)  # не прерывать финальное сохранение
            except (NotImplementedError, RuntimeError):
                pass
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await persister.save()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
