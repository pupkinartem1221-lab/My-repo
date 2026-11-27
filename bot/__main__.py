import asyncio
import logging
import os
import signal
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, ErrorEvent, MenuButtonCommands

from . import scheduler, ui
from .config import load_config
from .db import DB
from .fsm_storage import SQLiteStorage
from .handlers import clients, common, fallback, payments, reports, requisites, staff
from .middleware import AccessMiddleware
from .storage_sync import DataSync, LeaseLost
from .utils import TZ, now

log = logging.getLogger("crm")


class Persister:
    def __init__(self, db: DB, sync: DataSync):
        self.db = db
        self.sync = sync
        self.lock = asyncio.Lock()
        self.failures = 0
        self.lease_lost = False

    async def save(self) -> bool:
        """True — данные сохранены (или сохранять нечего)."""
        if not self.sync.enabled or self.lease_lost:
            return not self.lease_lost
        async with self.lock:
            if not self.db.dirty:
                return True
            self.db.dirty = False
            snap = self.db.path + ".snap"
            try:
                await self.db.snapshot(snap)
                await asyncio.to_thread(self.sync.save, snap)
                self.failures = 0
                return True
            except LeaseLost:
                self.lease_lost = True
                log.critical("Ветку с данными изменил другой экземпляр бота — работа остановлена, "
                             "чтобы не затереть чужие данные")
                return False
            except BaseException as e:
                self.db.dirty = True
                self.failures += 1
                if not isinstance(e, Exception):
                    raise
                log.error("Не удалось сохранить базу: %s", type(e).__name__ if not isinstance(e, RuntimeError) else e)
                return False
            finally:
                try:
                    os.remove(snap)
                except FileNotFoundError:
                    pass

    async def loop(self, interval: int, stop: asyncio.Event, on_fatal) -> None:
        alerted = False
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), interval)
            except asyncio.TimeoutError:
                # shield: отмена задачи не прерывает уже начатое сохранение
                await asyncio.shield(self.save())
                if self.lease_lost:
                    await on_fatal("⛔ Бот остановлен: данные изменил другой экземпляр бота. "
                                   "Проверьте, не запущен ли бот где-то ещё.")
                    return
                if self.failures >= 5 and not alerted:
                    alerted = True
                    await on_fatal(None)


def _log_crash(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Фоновая задача упала: %s", type(task.exception()).__name__, exc_info=task.exception())


async def main() -> None:
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # aiogram пишет в лог имя бота и содержимое ошибок — в публичном логе Actions это лишнее
    logging.getLogger("aiogram.event").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    cfg = load_config()
    sync = DataSync(cfg.data_repo, cfg.gh_token, cfg.data_branch, cfg.db_password,
                    cfg.db_password_old, cfg.init_db)
    await asyncio.to_thread(sync.load, cfg.db_path)

    db = DB(cfg.db_path)
    await db.connect()
    persister = Persister(db, sync)
    try:
        await run_bot(cfg, db, persister)
    finally:
        # финальное сохранение с повторами (до ~1 минуты)
        ok = True
        for attempt in range(4):
            ok = await persister.save()
            if ok or persister.lease_lost:
                break
            await asyncio.sleep(5 * (attempt + 1))
        await db.close()
        log.info("Остановлен")
        if not ok:
            raise SystemExit("Финальное сохранение не удалось")


def planned_stop_delay(run_seconds: int) -> float:
    """Не останавливаться в 23:40–00:05: в полночь должен работать бот, а не перезапуск."""
    stop_at = datetime.now(TZ) + timedelta(seconds=run_seconds)
    midnight = scheduler.next_midnight(stop_at - timedelta(minutes=5))
    if midnight - timedelta(minutes=20) <= stop_at <= midnight + timedelta(minutes=5):
        stop_at = midnight - timedelta(minutes=20)
    return max(60.0, (stop_at - datetime.now(TZ)).total_seconds())


def build_dispatcher(db: DB, cfg) -> Dispatcher:
    # SimpleEventIsolation: события одного пользователя обрабатываются по очереди
    # (двойное нажатие кнопки не создаёт дублей)
    dp = Dispatcher(storage=SQLiteStorage(db), events_isolation=SimpleEventIsolation())
    dp["db"] = db
    dp["cfg"] = cfg
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    dp.include_routers(common.router, clients.router, payments.router, requisites.router,
                       staff.router, reports.router, fallback.router)
    dp.errors.register(on_error)
    ui.init(db)
    return dp


async def on_error(event: ErrorEvent):
    exc = event.exception
    tb = exc.__traceback__
    while tb and tb.tb_next:
        tb = tb.tb_next
    where = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}" if tb else "?"
    log.error("Ошибка обработки: %s в %s", type(exc).__name__, where)  # без текста ошибки и данных
    upd = event.update
    try:
        if upd.callback_query:
            await upd.callback_query.answer("⚠️ Ошибка, попробуйте ещё раз", show_alert=True)
        elif upd.message:
            await upd.message.answer("⚠️ Ошибка. Попробуйте ещё раз или нажмите /menu")
    except Exception:
        pass
    return True


async def run_bot(cfg, db: DB, persister: Persister) -> None:
    # главный админ всегда есть в базе; прежний главный админ (если OWNER_ID сменили) становится сотрудником
    await db.run("UPDATE users SET role='worker' WHERE role='owner' AND (tg_id IS NULL OR tg_id<>?)",
                 cfg.owner_id)
    if await db.one("SELECT id FROM users WHERE tg_id=?", cfg.owner_id):
        await db.run("UPDATE users SET role='owner', approved=1 WHERE tg_id=?", cfg.owner_id)
    else:
        await db.run("INSERT INTO users(tg_id, role, percent, created_at, approved) VALUES (?, 'owner', 50, ?, 1)",
                     cfg.owner_id, now())

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                       link_preview_is_disabled=True))
    dp = build_dispatcher(db, cfg)
    try:
        # кнопка «Меню» слева от поля ввода в Telegram
        await bot.set_my_commands([BotCommand(command="menu", description="🏠 Главное меню"),
                                   BotCommand(command="cancel", description="✖️ Отменить действие")])
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        log.warning("Не удалось установить меню команд: %s", type(e).__name__)

    async def alert_owner(text: str | None):
        from .notify import send_safe
        await send_safe(bot, cfg.owner_id, text or "⚠️ Бот не может сохранить данные уже несколько минут. "
                                                    "Проверьте раздел Actions в GitHub.")
        if text:
            await dp.stop_polling()

    stop = asyncio.Event()
    persist_task = asyncio.create_task(persister.loop(cfg.save_interval, stop, alert_owner))
    other_tasks = [asyncio.create_task(scheduler.daily_loop(bot, db))]
    if cfg.run_seconds > 0:
        async def stop_later():
            await asyncio.sleep(planned_stop_delay(cfg.run_seconds))
            async with scheduler.send_lock:  # не прерывать рассылку итога дня
                log.info("Плановая остановка")
                await dp.stop_polling()
        other_tasks.append(asyncio.create_task(stop_later()))
    for t in (persist_task, *other_tasks):
        t.add_done_callback(_log_crash)

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
        # дождаться обработчиков, которые ещё работают (Telegram уже не пришлёт эти события повторно)
        inflight = [t for t in getattr(dp, "_handle_update_tasks", ()) if not t.done()]
        if inflight:
            await asyncio.wait(inflight, timeout=5)
        stop.set()
        for t in other_tasks:
            t.cancel()
        await asyncio.gather(persist_task, *other_tasks, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
