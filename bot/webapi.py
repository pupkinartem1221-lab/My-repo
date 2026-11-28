"""API для мини-приложения Telegram.

Каждый запрос подписан Telegram (заголовок X-Init-Data = Telegram.WebApp.initData).
Подпись проверяется токеном бота, поэтому подделать пользователя нельзя.
Права те же, что в боте: сотрудник видит только своих клиентов, админ — всё.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import timedelta
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiohttp import web

from .db import DB
from .handlers.staff import USERNAME_RE, can_approve, can_manage, can_set_percent
from .middleware import PENDING_TTL
from .notify import notify_admins, notify_all, notify_user, send_safe, with_hide
from .keyboards import btn, danger_btn, kb, main_btn, ok_btn
from .reports import PERIODS, period
from .rules import RECEIPT_REQUIRED, has_receipt, revert_paid_if_no_receipt, set_percent, worker_total
from .utils import (CLIENT_STATUSES, ROLES, TZ, day_range, deleted_req_label, esc, fmt_money, iban_ok, ipn_checksum_ok, is_admin,
                    like_escape, now, parse_money, today, user_name)

log = logging.getLogger(__name__)
MAX_AGE = 12 * 3600
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/pdf"}
PHONE = "replace(replace(replace(replace(replace(phone,'+',''),' ',''),'-',''),'(',''),')','')"
SHARE_SQL = "CAST(amount * COALESCE(worker_percent, 0) / 100.0 + 0.5 AS INTEGER)"


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        self.status, self.message, self.code = status, message, code


def check_init_data(init_data: str, token: str) -> dict | None:
    """Проверка подписи Telegram Mini App (https://core.telegram.org/bots/webapps)."""
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = data.pop("hash", None)
    if not received or not re.fullmatch(r"[0-9a-f]{64}", received):
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None
    try:
        if not -300 <= time.time() - int(data.get("auth_date", "0")) <= MAX_AGE:
            return None
        user = json.loads(data["user"])
        return user if isinstance(user, dict) and str(user.get("id", "")).isdigit() else None
    except (ValueError, KeyError):
        return None


def bad(message: str, status: int = 400, code: str | None = None):
    raise ApiError(status, message, code)


def as_id(value) -> int:
    if isinstance(value, bool) or not str(value).isdigit():
        bad("Неверные данные, обновите экран")
    return int(value)


def sniff_file(content: bytes):
    """Тип файла по содержимому (не доверяем тому, что прислал телефон)."""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "receipt.jpg", True
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "receipt.png", True
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", "receipt.webp", True
    if content[4:8] == b"ftyp" and content[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "image/heic", "receipt.heic", False   # HEIC Telegram не показывает как фото — отправим файлом
    if content.startswith(b"%PDF-"):
        return "application/pdf", "receipt.pdf", False
    return None


def need_admin(user):
    if not is_admin(user):
        bad("Нет доступа", 403)


def _bg(coro):
    task = asyncio.create_task(coro)
    task.add_done_callback(lambda t: t.cancelled() or not t.exception() or
                           log.warning("Уведомление не отправлено: %s", type(t.exception()).__name__))


def user_json(u):
    return {"id": u["id"], "nick": u["nick"], "username": u["username"], "role": u["role"],
            "percent": u["percent"], "approved": bool(u["approved"]), "connected": bool(u["tg_id"])}


def req_json(r):
    return None if r is None else {"id": r["id"], "iban": r["iban"], "holder": r["holder"], "ipn": r["ipn"],
                                   "comment": r["comment"], "active": bool(r["is_active"])}


class Api:
    def __init__(self, db: DB, bot: Bot, token: str, allowed_origin: str | None, static_dir: str | None = None):
        self.db, self.bot, self.token, self.origin = db, bot, token, allowed_origin
        self.static_dir = static_dir
        self.hits: dict[int, list[float]] = {}
        self.upload_sem = asyncio.Semaphore(3)

    def rate(self, uid: int, limit: int, window: int):
        t = time.monotonic()
        q = [x for x in self.hits.get(uid, []) if t - x < window]
        if len(q) >= limit:
            bad("Слишком часто, подождите минуту", 429)
        q.append(t)
        self.hits[uid] = q

    # ---------- инфраструктура ----------

    def cors(self, resp, request):
        if self.origin and request.headers.get("Origin") == self.origin:
            resp.headers["Access-Control-Allow-Origin"] = self.origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "X-Init-Data, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Max-Age"] = "600"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @web.middleware
    async def middleware(self, request, handler):
        if request.method == "OPTIONS":
            return self.cors(web.Response(status=204), request)
        try:
            if request.path.startswith("/api/") and request.path != "/api/health":
                tg = check_init_data(request.headers.get("X-Init-Data", ""), self.token)
                if tg is None:
                    bad("Откройте приложение из Telegram", 401)
                user = await self.db.one("SELECT * FROM users WHERE tg_id=?", int(tg["id"]))
                if user is None or not user["approved"] or not user["nick"]:
                    bad("Нет доступа. Сначала откройте бота и нажмите /start", 403)
                request["user"] = user
            resp = await handler(request)
        except ApiError as e:
            resp = web.json_response({"error": e.message, "code": e.code}, status=e.status)
        except web.HTTPException as e:
            resp = web.json_response({"error": e.reason}, status=e.status)
        except Exception as e:
            log.error("API ошибка: %s", type(e).__name__)
            resp = web.json_response({"error": "Ошибка сервера, попробуйте ещё раз"}, status=500)
        return self.cors(resp, request)

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.middleware], client_max_size=21 * 1024 * 1024)
        r = app.router
        r.add_get("/api/health", lambda req: web.json_response({"ok": True}))
        r.add_get("/api/me", self.me)
        r.add_get("/api/dashboard", self.dashboard)
        r.add_get("/api/clients", self.clients)
        r.add_post("/api/clients", self.client_create)
        r.add_get("/api/clients/{id:\\d+}", self.client_get)
        r.add_patch("/api/clients/{id:\\d+}", self.client_patch)
        r.add_delete("/api/clients/{id:\\d+}", self.client_delete)
        r.add_post("/api/clients/{id:\\d+}/comments", self.comment_add)
        r.add_post("/api/clients/{id:\\d+}/payments", self.payment_create)
        r.add_get("/api/payments", self.payments)
        r.add_post("/api/payments/{id:\\d+}/review", self.payment_review)
        r.add_delete("/api/payments/{id:\\d+}", self.payment_delete)
        r.add_get("/api/payments/{id:\\d+}/file", self.payment_file)
        r.add_get("/api/requisites", self.requisites)
        r.add_post("/api/requisites", self.requisite_create)
        r.add_patch("/api/requisites/{id:\\d+}", self.requisite_patch)
        r.add_delete("/api/requisites/{id:\\d+}", self.requisite_delete)
        r.add_get("/api/team", self.team)
        r.add_post("/api/team", self.team_invite)
        r.add_patch("/api/team/{id:\\d+}", self.team_patch)
        r.add_post("/api/team/{id:\\d+}/approve", self.team_approve)
        r.add_delete("/api/team/{id:\\d+}", self.team_delete)
        r.add_get("/api/reports", self.reports)
        r.add_get("/api/audit", self.audit)
        if self.static_dir:  # приложение можно открыть и прямо через туннель (если GitHub Pages не включён)
            r.add_get("/app", lambda req: web.HTTPFound("/app/"))
            r.add_get("/app/", lambda req: web.FileResponse(f"{self.static_dir}/index.html"))
            r.add_static("/app/", self.static_dir)
        return app

    async def body(self, request) -> dict:
        if (request.content_length or 0) > 64 * 1024:
            bad("Слишком большой запрос", 413)
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            bad("Неверный запрос")
        if not isinstance(data, dict):
            bad("Неверный запрос")
        return data

    async def client_for(self, user, cid: int):
        c = await self.db.one("SELECT * FROM clients WHERE id=?", cid)
        if c is None or not (is_admin(user) or c["worker_id"] == user["id"]):
            bad("Клиент не найден", 404)
        return c

    # ---------- профиль и главная ----------

    async def me(self, request):
        u = request["user"]
        return web.json_response({"user": user_json(u), "admin": is_admin(u), "owner": u["role"] == "owner",
                                  "statuses": CLIENT_STATUSES, "periods": PERIODS})

    async def dashboard(self, request):
        u, db = request["user"], self.db
        admin = is_admin(u)
        scope, sp = ("", []) if admin else (" AND worker_id=?", [u["id"]])
        t = today()
        week = []
        for i in range(6, -1, -1):
            d = t - timedelta(days=i)
            s, e = day_range(d)
            row = await db.one(f"SELECT COUNT(*) n, COALESCE(SUM(amount),0) a, COALESCE(SUM(worker_share),0) sh "
                               f"FROM payments WHERE status='confirmed' AND reviewed_at>=? AND reviewed_at<?{scope}",
                               s, e, *sp)
            week.append({"label": d.strftime("%d.%m"), "amount": row["a"], "share": row["sh"], "count": row["n"]})
        pscope, pp = ("", []) if admin else (" AND (worker_id=? OR submitted_by=?)", [u["id"], u["id"]])
        pend = await db.one(f"SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments WHERE status='pending'{pscope}", *pp)
        cscope, cp = ("", []) if admin else (" WHERE worker_id=?", [u["id"]])
        clients = await db.one(f"SELECT COUNT(*) n, SUM(status='work') w, "
                               f"SUM(status='work' AND requisite_id IS NULL) noreq FROM clients{cscope}", *cp)
        recent = await db.all(
            f"SELECT p.id, p.client_id, p.client_name, p.amount, p.worker_share, p.reviewed_at, w.nick wnick "
            f"FROM payments p LEFT JOIN users w ON w.id=p.worker_id WHERE p.status='confirmed'"
            f"{'' if admin else ' AND p.worker_id=?'} ORDER BY p.reviewed_at DESC LIMIT 5", *sp)
        result = {
            "today": week[-1], "yesterday": week[-2], "week": week,
            "pending": {"count": pend["n"], "amount": pend["s"]},
            "clients": {"total": clients["n"], "work": clients["w"] or 0, "no_requisite": clients["noreq"] or 0},
            "recent": [{"id": r["id"], "client_id": r["client_id"], "client_name": r["client_name"], "amount": r["amount"],
                        "share": r["worker_share"], "at": r["reviewed_at"], "worker": r["wnick"]} for r in recent],
        }
        if admin:
            result["waiting_access"] = (await db.one(
                "SELECT COUNT(*) n FROM users WHERE tg_id IS NOT NULL AND approved=0"))["n"]
        return web.json_response(result)

    # ---------- клиенты ----------

    async def clients(self, request):
        u = request["user"]
        q = " ".join(request.query.get("q", "").split())[:100]
        status = request.query.get("status", "")
        where, params = [], []
        if not is_admin(u):
            where.append("c.worker_id=?")
            params.append(u["id"])
        if status in CLIENT_STATUSES:
            where.append("c.status=?")
            params.append(status)
        if q:
            digits = re.sub(r"\D", "", q)
            where.append(f"(ulower(c.name) LIKE ? ESCAPE '\\' OR (? <> '' AND {PHONE} LIKE ?))")
            params += [f"%{like_escape(q.lower())}%", digits if len(digits) >= 3 else "", f"%{digits}%"]
        w = ("WHERE " + " AND ".join(where)) if where else ""
        rows = await self.db.all(
            f"SELECT c.*, u.nick wnick, (SELECT COALESCE(SUM(amount),0) FROM payments p WHERE p.client_id=c.id "
            f"AND p.status='confirmed') paid FROM clients c LEFT JOIN users u ON u.id=c.worker_id {w} "
            "ORDER BY c.id DESC LIMIT 200", *params)
        counts = await self.db.all(
            "SELECT status, COUNT(*) n FROM clients" + ("" if is_admin(u) else " WHERE worker_id=?") + " GROUP BY status",
            *([] if is_admin(u) else [u["id"]]))
        return web.json_response({
            "items": [{"id": c["id"], "name": c["name"], "phone": c["phone"], "status": c["status"],
                       "worker": c["wnick"], "paid": c["paid"], "created_at": c["created_at"]} for c in rows],
            "counts": {r["status"]: r["n"] for r in counts},
        })

    async def client_create(self, request):
        u, db = request["user"], self.db
        data = await self.body(request)
        name = " ".join(str(data.get("name", "")).split())
        phone = " ".join(str(data.get("phone", "")).split())
        comment = str(data.get("comment") or "").strip()[:1500]
        if not 1 <= len(name) <= 100:
            bad("Укажите имя (до 100 символов)")
        if not re.fullmatch(r"\+?[\d\s\-()]{7,25}", phone) or len(re.sub(r"\D", "", phone)) < 7:
            bad("Проверьте телефон")
        worker_id = u["id"]
        if is_admin(u) and data.get("worker_id"):
            w = await db.one("SELECT id FROM users WHERE id=? AND nick IS NOT NULL AND approved=1", as_id(data["worker_id"]))
            if w is None:
                bad("Сотрудник не найден")
            worker_id = w["id"]
        cur = await db.run("INSERT INTO clients(name, phone, worker_id, status, created_by, created_at) "
                           "VALUES (?, ?, ?, 'work', ?, ?)", name, phone, worker_id, u["id"], now())
        cid = cur.lastrowid
        if comment:
            await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                         cid, u["id"], comment, now())
        worker = await db.get_user(worker_id)
        await db.audit(u["id"], f"Добавил клиента #{cid} {name} (сотрудник {worker['nick']}) [приложение]")
        open_kb = kb([main_btn("👤 Открыть", f"cl:v:{cid}")])
        _bg(notify_admins(self.bot, db, f"🆕 <b>{esc(name)}</b> · {esc(phone)}\n👷 {user_name(worker)}",
                          exclude_user_id=u["id"], reply_markup=open_kb))
        if worker_id != u["id"] and worker["role"] == "worker":
            _bg(notify_user(self.bot, db, worker_id, f"📥 Новый клиент: <b>{esc(name)}</b>", open_kb))
        return web.json_response({"id": cid}, status=201)

    async def client_get(self, request):
        u, db = request["user"], self.db
        c = await self.client_for(u, int(request.match_info["id"]))
        worker = await db.get_user(c["worker_id"])
        req = await db.one("SELECT * FROM requisites WHERE id=?", c["requisite_id"]) if c["requisite_id"] else None
        comments = await db.all("SELECT cm.*, u.nick FROM comments cm LEFT JOIN users u ON u.id=cm.author_id "
                                "WHERE client_id=? ORDER BY cm.id DESC LIMIT 100", c["id"])
        pays = await db.all("SELECT * FROM payments WHERE client_id=? ORDER BY id DESC", c["id"])
        result = {
            "id": c["id"], "name": c["name"], "phone": c["phone"], "status": c["status"],
            "created_at": c["created_at"], "worker": user_json(worker) if worker else None,
            "requisite": req_json(req),
            "paid": sum(p["amount"] for p in pays if p["status"] == "confirmed"),
            "pending": sum(p["amount"] for p in pays if p["status"] == "pending"),
            "comments": [{"id": x["id"], "text": x["text"], "author": x["nick"], "at": x["created_at"]} for x in comments],
            "payments": [self.payment_json(p, u) for p in pays],
            "can_manage": is_admin(u),
        }
        return web.json_response(result)

    async def client_patch(self, request):
        u, db = request["user"], self.db
        c = await self.client_for(u, int(request.match_info["id"]))
        data = await self.body(request)
        if "name" in data or "phone" in data:
            name = " ".join(str(data.get("name", c["name"])).split())
            phone = " ".join(str(data.get("phone", c["phone"] or "")).split())
            if not 1 <= len(name) <= 100:
                bad("Укажите имя (до 100 символов)")
            if not re.fullmatch(r"\+?[\d\s\-()]{7,25}", phone) or len(re.sub(r"\D", "", phone)) < 7:
                bad("Проверьте телефон")
            if (name, phone) != (c["name"], c["phone"]):
                await db.run("UPDATE clients SET name=?, phone=? WHERE id=?", name, phone, c["id"])
                await db.audit(u["id"], f"Клиент #{c['id']}: изменены данные [приложение]")
        if "status" in data:
            st = data["status"]
            if st not in CLIENT_STATUSES:
                bad("Неизвестный статус")
            if st == "paid" and st != c["status"] and not await has_receipt(db, c["id"]):
                bad(RECEIPT_REQUIRED, 409, "receipt_required")
            if st != c["status"]:
                await db.run("UPDATE clients SET status=? WHERE id=?", st, c["id"])
                old, new = CLIENT_STATUSES[c["status"]], CLIENT_STATUSES[st]
                await db.audit(u["id"], f"Клиент #{c['id']}: {old} → {new} [приложение]")
                _bg(notify_admins(self.bot, db, f"🔁 {user_name(u)}: {esc(c['name'])} → <b>{new}</b>",
                                  exclude_user_id=u["id"], reply_markup=kb([main_btn("👤 Открыть", f"cl:v:{c['id']}")])))
        if "requisite_id" in data:
            rid = data["requisite_id"]
            if rid:
                r = await db.one("SELECT id FROM requisites WHERE id=? AND is_active=1", as_id(rid))
                if r is None:
                    bad("Реквизит нерабочий или удалён")
                rid = r["id"]
            await db.run("UPDATE clients SET requisite_id=? WHERE id=?", rid or None, c["id"])
            await db.audit(u["id"], f"Клиент #{c['id']}: реквизит → {('#' + str(rid)) if rid else 'отвязан'} [приложение]")
        if "worker_id" in data:
            need_admin(u)
            w = await db.one("SELECT * FROM users WHERE id=? AND nick IS NOT NULL AND approved=1", as_id(data["worker_id"]))
            if w is None:
                bad("Сотрудник не найден")
            if w["id"] != c["worker_id"]:
                await db.run_many([
                    ("UPDATE clients SET worker_id=? WHERE id=?", w["id"], c["id"]),
                    ("UPDATE payments SET worker_id=? WHERE client_id=? AND status='pending'", w["id"], c["id"]),
                ])
                await db.audit(u["id"], f"Клиент #{c['id']} передан {w['nick']} [приложение]")
                if c["worker_id"] and c["worker_id"] not in (u["id"], w["id"]):
                    _bg(notify_user(self.bot, db, c["worker_id"], f"📤 Клиент {esc(c['name'])} передан другому сотруднику."))
                if w["id"] != u["id"]:
                    _bg(notify_user(self.bot, db, w["id"], f"📥 Вам передан клиент <b>{esc(c['name'])}</b>",
                                    kb([main_btn("👤 Открыть", f"cl:v:{c['id']}")])))
        return web.json_response({"ok": True})

    async def client_delete(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        c = await self.client_for(u, int(request.match_info["id"]))
        await db.run("DELETE FROM clients WHERE id=?", c["id"])
        await db.audit(u["id"], f"Удалил клиента #{c['id']} {c['name']} [приложение]")
        _bg(notify_admins(self.bot, db, f"🗑 {user_name(u)} удалил клиента {esc(c['name'])}", exclude_user_id=u["id"]))
        return web.json_response({"ok": True})

    async def comment_add(self, request):
        u, db = request["user"], self.db
        c = await self.client_for(u, int(request.match_info["id"]))
        text = str((await self.body(request)).get("text", "")).strip()
        if not text:
            bad("Пустой комментарий")
        cur = await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                           c["id"], u["id"], text[:1500], now())
        await db.audit(u["id"], f"Комментарий к клиенту #{c['id']} [приложение]")
        return web.json_response({"id": cur.lastrowid, "text": text[:1500], "author": u["nick"], "at": now()},
                                 status=201)

    # ---------- квитанции ----------

    def payment_json(self, p, viewer):
        show_share = is_admin(viewer) or p["worker_id"] == viewer["id"]
        return {"id": p["id"], "amount": p["amount"], "status": p["status"], "client_id": p["client_id"],
                "client_name": p["client_name"], "requisite": p["requisite_label"],
                "file_type": p["file_type"], "submitted_at": p["submitted_at"], "reviewed_at": p["reviewed_at"],
                "share": p["worker_share"] if show_share else None,
                "percent": p["worker_percent"] if show_share else None}

    async def payments(self, request):
        u, db = request["user"], self.db
        status = request.query.get("status", "pending")
        if status not in ("pending", "confirmed", "rejected"):
            bad("Неизвестный статус")
        where, params = "p.status=?", [status]
        if not is_admin(u):
            where += " AND (p.worker_id=? OR p.submitted_by=?)"
            params += [u["id"], u["id"]]
        rows = await db.all(f"SELECT p.*, w.nick wnick, s.nick snick, r.nick rnick, c.phone cphone FROM payments p "
                            "LEFT JOIN users w ON w.id=p.worker_id LEFT JOIN users s ON s.id=p.submitted_by "
                            "LEFT JOIN users r ON r.id=p.reviewed_by LEFT JOIN clients c ON c.id=p.client_id "
                            f"WHERE {where} ORDER BY p.id {'ASC' if status == 'pending' else 'DESC'} LIMIT 100",
                            *params)
        items = []
        for p in rows:
            j = self.payment_json(p, u)
            j.update(worker=p["wnick"], submitter=p["snick"], reviewer=p["rnick"], phone=p["cphone"])
            items.append(j)
        return web.json_response({"items": items})

    async def payment_create(self, request):
        u, db = request["user"], self.db
        c = await self.client_for(u, int(request.match_info["id"]))
        self.rate(u["id"], 10, 60)
        if (request.content_length or 0) > 21 * 1024 * 1024:
            bad("Файл слишком большой (до 20 МБ)", 413)
        try:
            form = await request.post()
        except ValueError:
            bad("Файл слишком большой (до 20 МБ)")
        f = form.get("file")
        amount = parse_money(str(form.get("amount", "")))
        if amount is None:
            bad("Проверьте сумму")
        if f is None or not hasattr(f, "file"):
            bad("Добавьте фото квитанции")
        content = f.file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            bad("Файл слишком большой (до 20 МБ)")
        sniffed = sniff_file(content)
        if sniffed is None:
            bad("Нужно фото или PDF квитанции")
        mime, name, is_photo = sniffed
        rid = form.get("requisite_id") or c["requisite_id"]
        req = await db.one("SELECT * FROM requisites WHERE id=?", as_id(rid)) if rid else None
        if rid and form.get("requisite_id") and (req is None or not req["is_active"]):
            bad("Реквизит нерабочий")

        # Файл храним в Telegram: отправляем его админам (это и есть уведомление) и берём file_id.
        admins = await db.all("SELECT * FROM users WHERE role IN ('owner','admin') AND tg_id IS NOT NULL "
                              "AND approved=1 ORDER BY id<>? , id", u["id"])
        file_id, file_type, first_msg = None, ("photo" if is_photo else "document"), None
        caption = f"🔔 Новая квитанция · {fmt_money(amount)}\n👤 {esc(c['name'])}\n👷 {user_name(u)}"
        for a in admins:
            try:
                upload = BufferedInputFile(content, filename=name)
                if is_photo:
                    m = await self.bot.send_photo(a["tg_id"], upload, caption=caption)
                    file_id = m.photo[-1].file_id
                else:
                    m = await self.bot.send_document(a["tg_id"], upload, caption=caption)
                    file_id = m.document.file_id
                first_msg = (a, m)
                break
            except Exception:
                continue
        if file_id is None:
            bad("Не удалось сохранить файл, попробуйте ещё раз", 502)

        label = f"{req['iban']} ({req['holder']})" if req else None
        cur = await db.run(
            "INSERT INTO payments(client_id, client_name, requisite_id, requisite_label, worker_id, amount, "
            "file_id, file_type, status, submitted_by, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            c["id"], c["name"], req["id"] if req else None, label, c["worker_id"], amount, file_id, file_type,
            u["id"], now())
        pid = cur.lastrowid
        if req and not c["requisite_id"] and req["is_active"]:
            await db.run("UPDATE clients SET requisite_id=? WHERE id=?", req["id"], c["id"])
        await db.audit(u["id"], f"Квитанция #{pid}: клиент #{c['id']}, {fmt_money(amount)} [приложение]")
        if form.get("set_paid") == "1" and c["status"] != "paid":
            await db.run("UPDATE clients SET status='paid' WHERE id=?", c["id"])
            await db.audit(u["id"], f"Клиент #{c['id']}: → ✅ Оплачено (с квитанцией #{pid}) [приложение]")

        review = kb([ok_btn("✅ Подтвердить", f"pay:ok:{pid}"), danger_btn("❌ Отклонить", f"pay:no:{pid}")],
                    [btn("👤 Клиент", f"cl:v:{c['id']}")])
        a, m = first_msg
        try:
            if a["id"] == u["id"]:
                await m.delete()  # своему же админу дублировать не нужно
            else:
                await m.edit_reply_markup(reply_markup=with_hide(review))
        except Exception:
            pass

        async def rest():
            for other in admins:
                if other["id"] in (a["id"], u["id"]):
                    continue
                try:
                    if file_type == "photo":
                        await self.bot.send_photo(other["tg_id"], file_id, caption=caption, reply_markup=with_hide(review))
                    else:
                        await self.bot.send_document(other["tg_id"], file_id, caption=caption,
                                                     reply_markup=with_hide(review))
                except Exception:
                    pass
                await asyncio.sleep(0.05)
        _bg(rest())
        return web.json_response({"id": pid}, status=201)

    async def payment_review(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        pid = int(request.match_info["id"])
        action = (await self.body(request)).get("action")
        if action not in ("ok", "no"):
            bad("Неизвестное действие")
        if action == "ok":
            cur = await db.run(
                "UPDATE payments SET status='confirmed', reviewed_by=?, reviewed_at=?, "
                "worker_percent=(SELECT percent FROM users WHERE users.id=payments.worker_id) "
                "WHERE id=? AND status='pending'", u["id"], now(), pid)
            if cur.rowcount:
                await db.run(f"UPDATE payments SET worker_share={SHARE_SQL} WHERE id=?", pid)
        else:
            cur = await db.run("UPDATE payments SET status='rejected', reviewed_by=?, reviewed_at=? "
                               "WHERE id=? AND status='pending'", u["id"], now(), pid)
        p = await db.one("SELECT * FROM payments WHERE id=?", pid)
        if p is None:
            bad("Квитанция удалена", 404)
        if cur.rowcount == 0:
            bad("Уже проверена", 409)
        name, amount = esc(p["client_name"]), fmt_money(p["amount"])
        if action == "ok":
            if p["client_id"]:
                await db.run("UPDATE clients SET status='paid' WHERE id=?", p["client_id"])
            await db.audit(u["id"], f"Подтвердил квитанцию #{pid} ({amount}) [приложение]")
            worker_text = f"✅ Оплата подтверждена: {name} · {amount}\n💵 Ваш заработок: <b>{fmt_money(p['worker_share'])}</b>"
            sub_text = f"✅ Оплата подтверждена: {name} · {amount}"
            other = f"✅ {user_name(u)} подтвердил: {name} · {amount}"
        else:
            await db.audit(u["id"], f"Отклонил квитанцию #{pid} ({amount}) [приложение]")
            worker_text = sub_text = f"❌ Квитанция отклонена: {name} · {amount}"
            if await revert_paid_if_no_receipt(db, p["client_id"]):
                worker_text = sub_text = worker_text + "\nСтатус клиента вернулся в 🔄 В работе"
            other = f"❌ {user_name(u)} отклонил: {name} · {amount}"
        open_kb = kb([main_btn("👤 Открыть клиента", f"cl:v:{p['client_id']}")]) if p["client_id"] else None

        async def notify():
            done = {u["id"]}
            for uid, text in ((p["worker_id"], worker_text), (p["submitted_by"], sub_text)):
                if uid and uid not in done:
                    t = await db.get_user(uid)
                    if t and not is_admin(t):
                        await notify_user(self.bot, db, uid, text, open_kb)
                    done.add(uid)
            await notify_admins(self.bot, db, other, exclude_user_id=u["id"])
        _bg(notify())
        return web.json_response(self.payment_json(p, u))

    async def payment_delete(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        pid = int(request.match_info["id"])
        p = await db.one("SELECT * FROM payments WHERE id=?", pid)
        if p is None or (await db.run("DELETE FROM payments WHERE id=?", pid)).rowcount == 0:
            bad("Уже удалена", 404)
        await revert_paid_if_no_receipt(db, p["client_id"])  # «Оплачено» без квитанции не остаётся
        await db.audit(u["id"], f"Удалил квитанцию #{pid} ({fmt_money(p['amount'])}, {p['status']}) [приложение]")
        if p["status"] == "confirmed" and p["worker_id"] and p["worker_id"] != u["id"]:
            _bg(notify_user(self.bot, db, p["worker_id"], f"⚠️ Удалена квитанция: {esc(p['client_name'])} · "
                            f"{fmt_money(p['amount'])}\nВаш заработок уменьшился на {fmt_money(p['worker_share'])}"))
        _bg(notify_admins(self.bot, db, f"🗑 {user_name(u)} удалил квитанцию {esc(p['client_name'])} · "
                                        f"{fmt_money(p['amount'])}", exclude_user_id=u["id"]))
        return web.json_response({"ok": True})

    async def payment_file(self, request):
        u, db = request["user"], self.db
        p = await db.one("SELECT * FROM payments WHERE id=?", int(request.match_info["id"]))
        if p is None:
            bad("Не найдено", 404)
        allowed = is_admin(u) or p["submitted_by"] == u["id"] or p["worker_id"] == u["id"]
        if not allowed and p["client_id"]:
            c = await db.one("SELECT worker_id FROM clients WHERE id=?", p["client_id"])
            allowed = bool(c and c["worker_id"] == u["id"])
        if not allowed:
            bad("Не найдено", 404)
        f = await self.bot.get_file(p["file_id"])
        data = await self.bot.download_file(f.file_path)
        ctype = "image/jpeg" if p["file_type"] == "photo" else (
            "application/pdf" if (f.file_path or "").lower().endswith(".pdf") else "application/octet-stream")
        headers = {"Content-Security-Policy": "default-src 'none'; sandbox"}
        if not ctype.startswith("image/"):
            headers["Content-Disposition"] = "attachment; filename=receipt.pdf"
        return web.Response(body=data.read(), content_type=ctype, headers=headers)

    # ---------- реквизиты ----------

    async def requisites(self, request):
        u, db = request["user"], self.db
        rows = await db.all("SELECT * FROM requisites " + ("" if is_admin(u) else "WHERE is_active=1 ")
                            + "ORDER BY is_active DESC, id DESC")
        items = []
        s, e = day_range(today())
        for r in rows:
            j = req_json(r)
            if is_admin(u):
                t = await db.one("SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM payments "
                                 "WHERE requisite_id=? AND status='confirmed'", r["id"])
                d = await db.one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE requisite_id=? "
                                 "AND status='confirmed' AND reviewed_at>=? AND reviewed_at<?", r["id"], s, e)
                cl = await db.one("SELECT COUNT(*) n FROM clients WHERE requisite_id=?", r["id"])
                j.update(total=t["s"], count=t["n"], today=d["s"], clients=cl["n"])
            items.append(j)
        return web.json_response({"items": items})

    async def requisite_create(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        data = await self.body(request)
        iban = re.sub(r"\s+", "", str(data.get("iban", ""))).upper()
        holder = " ".join(str(data.get("holder", "")).split())
        ipn = re.sub(r"\s+", "", str(data.get("ipn", "")))
        comment = str(data.get("comment") or "").strip()[:500] or None
        if not iban_ok(iban):
            bad("IBAN с ошибкой — проверьте цифры")
        if not 3 <= len(holder) <= 120:
            bad("Укажите ФИО получателя")
        if not re.fullmatch(r"\d{10}", ipn):
            bad("ІПН — 10 цифр")
        cur = await db.run("INSERT INTO requisites(iban, holder, ipn, comment, is_active, created_by, created_at) "
                           "VALUES (?, ?, ?, ?, 1, ?, ?)", iban, holder, ipn, comment, u["id"], now())
        await db.audit(u["id"], f"Добавил реквизит #{cur.lastrowid} {iban} [приложение]")
        _bg(notify_admins(self.bot, db, f"➕ {user_name(u)} добавил реквизит …{esc(iban[-6:])} {esc(holder)}",
                          exclude_user_id=u["id"]))
        return web.json_response({"id": cur.lastrowid, "ipn_warning": not ipn_checksum_ok(ipn)}, status=201)

    async def requisite_patch(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        rid = int(request.match_info["id"])
        r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
        if r is None:
            bad("Реквизит не найден", 404)
        data = await self.body(request)
        if "active" in data:
            new = 1 if data["active"] else 0
            if new != r["is_active"]:
                await db.run("UPDATE requisites SET is_active=? WHERE id=?", new, rid)
                status = "🟢 рабочий" if new else "🔴 нерабочий"
                await db.audit(u["id"], f"Реквизит #{rid} → {status} [приложение]")
                _bg(notify_all(self.bot, db, f"💳 …{esc(r['iban'][-6:])} {esc(r['holder'])} — теперь <b>{status}</b>",
                               exclude_user_id=u["id"]))
        if "comment" in data:
            await db.run("UPDATE requisites SET comment=? WHERE id=?", str(data["comment"] or "").strip()[:500] or None, rid)
            await db.audit(u["id"], f"Изменил комментарий реквизита #{rid} [приложение]")
        return web.json_response({"ok": True})

    async def requisite_delete(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        rid = int(request.match_info["id"])
        r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
        if r is None:
            bad("Уже удалён", 404)
        await db.run("DELETE FROM requisites WHERE id=?", rid)
        await db.audit(u["id"], f"Удалил реквизит #{rid} {r['iban']} [приложение]")
        _bg(notify_admins(self.bot, db, f"🗑 {user_name(u)} удалил реквизит …{esc(r['iban'][-6:])}",
                          exclude_user_id=u["id"]))
        return web.json_response({"ok": True})

    # ---------- команда ----------

    async def team(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        rows = await db.all("SELECT u.*, (SELECT COUNT(*) FROM clients c WHERE c.worker_id=u.id) clients, "
                            "(SELECT COUNT(*) FROM clients c WHERE c.worker_id=u.id AND c.status='work') work "
                            "FROM users u ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, id")
        items = []
        for x in rows:
            j = user_json(x)
            if not x["tg_id"]:
                j["state"] = "expired" if x["created_at"] < now() - PENDING_TTL else "invited"
            elif not x["approved"]:
                j["state"] = "waiting"
            elif not x["nick"]:
                j["state"] = "no_nick"
            else:
                j["state"] = "active"
            j.update(clients=x["clients"], work=x["work"], can_manage=can_manage(u, x),
                     can_percent=can_set_percent(u, x), can_approve=can_approve(u, x))
            items.append(j)
        return web.json_response({"items": items, "can_invite_admin": u["role"] == "owner"})

    async def team_invite(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        data = await self.body(request)
        role = data.get("role", "worker")
        if role not in ("worker", "admin") or (role == "admin" and u["role"] != "owner"):
            bad("Нет доступа", 403)
        username = re.sub(r"^(https?://)?t\.me/", "", str(data.get("username", "")).strip().lower()).lstrip("@")
        if not USERNAME_RE.fullmatch(username):
            bad("Это не похоже на @username")
        existing = await db.one("SELECT * FROM users WHERE username=?", username)
        if existing and not (existing["tg_id"] is None and existing["created_at"] < now() - PENDING_TTL):
            bad("Этот человек уже в команде")
        if existing:
            await db.run("DELETE FROM users WHERE id=?", existing["id"])
        cur = await db.run("INSERT INTO users(username, role, percent, added_by, created_at, approved) "
                           "VALUES (?, ?, 50, ?, ?, 0)", username, role, u["id"], now())
        await db.audit(u["id"], f"Пригласил {ROLES[role]} @{username} [приложение]")
        _bg(notify_admins(self.bot, db, f"➕ {user_name(u)} пригласил {ROLES[role]} @{esc(username)}",
                          exclude_user_id=u["id"]))
        return web.json_response({"id": cur.lastrowid}, status=201)

    async def team_patch(self, request):
        u, db = request["user"], self.db
        t = await db.get_user(int(request.match_info["id"]))
        if t is None:
            bad("Сотрудник не найден", 404)
        data = await self.body(request)
        if "percent" in data:
            if not can_set_percent(u, t):
                bad("Нет доступа", 403)
            try:
                value = round(float(data["percent"]), 2)
            except (TypeError, ValueError):
                value = -1
            if not 0 <= value <= 100:
                bad("Нужно число от 0 до 100")
            n = await set_percent(db, t["id"], value)
            total = await worker_total(db, t["id"])
            await db.audit(u["id"], f"Процент {t['nick'] or t['username']}: {t['percent']:g}% → {value:g}% "
                                    f"(пересчитано оплат: {n}) [приложение]")
            if t["id"] != u["id"] and t["tg_id"]:
                _bg(send_safe(self.bot, t["tg_id"], f"💯 Ваш процент теперь <b>{value:g}%</b>\n"
                                                    f"Заработок пересчитан: <b>{fmt_money(total)}</b>"))
            _bg(notify_admins(self.bot, db, f"💯 {user_name(u)}: процент {user_name(t)} {t['percent']:g}% → {value:g}%",
                              exclude_user_id=u["id"]))
            return web.json_response({"ok": True, "recalculated": n, "total": total})
        return web.json_response({"ok": True})

    async def team_approve(self, request):
        u, db = request["user"], self.db
        t = await db.get_user(int(request.match_info["id"]))
        if t is None:
            bad("Запрос уже обработан", 409)
        if not can_approve(u, t):
            bad("Нет доступа", 403)
        if t["approved"] or not t["tg_id"]:
            bad("Запрос уже обработан", 409)
        ok = bool((await self.body(request)).get("ok"))
        name = "@" + (t["username"] or "?")
        if ok:
            if (await db.run("UPDATE users SET approved=1 WHERE id=? AND approved=0", t["id"])).rowcount != 1:
                bad("Запрос уже обработан", 409)
            await db.audit(u["id"], f"Подтвердил доступ {name} ({ROLES[t['role']]}) [приложение]")
            _bg(send_safe(self.bot, t["tg_id"], "✅ Доступ открыт! Нажмите /start"))
            _bg(notify_admins(self.bot, db, f"✅ {user_name(u)} подтвердил доступ {esc(name)}", exclude_user_id=u["id"]))
        else:
            await db.run("DELETE FROM users WHERE id=? AND approved=0", t["id"])
            await db.run("DELETE FROM fsm WHERE key LIKE ?", f"%:{t['tg_id']}:{t['tg_id']}:%")
            await db.run("DELETE FROM ui WHERE tg_id=?", t["tg_id"])
            await db.audit(u["id"], f"Отклонил доступ {name} (Telegram ID {t['tg_id']}) [приложение]")
            _bg(notify_admins(self.bot, db, f"❌ {user_name(u)} отклонил доступ {esc(name)}", exclude_user_id=u["id"]))
        return web.json_response({"ok": True})

    async def team_delete(self, request):
        u, db = request["user"], self.db
        t = await db.get_user(int(request.match_info["id"]))
        if t is None or not can_manage(u, t):
            bad("Нет доступа", 403)
        if t["tg_id"]:
            await db.run("DELETE FROM fsm WHERE key LIKE ?", f"%:{t['tg_id']}:{t['tg_id']}:%")
            await db.run("DELETE FROM ui WHERE tg_id=?", t["tg_id"])
        await db.run("DELETE FROM users WHERE id=?", t["id"])
        name = t["nick"] or t["username"]
        await db.audit(u["id"], f"Удалил {ROLES[t['role']]} {name} [приложение]")
        _bg(notify_admins(self.bot, db, f"🗑 {user_name(u)} удалил {esc(name)}", exclude_user_id=u["id"]))
        return web.json_response({"ok": True})

    # ---------- журнал ----------

    async def audit(self, request):
        u, db = request["user"], self.db
        need_admin(u)
        rows = await db.all("SELECT a.text, a.created_at, u.nick FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                            "ORDER BY a.id DESC LIMIT 150")
        return web.json_response({"items": [{"text": r["text"], "at": r["created_at"], "who": r["nick"]} for r in rows]})

    # ---------- отчёты ----------

    async def reports(self, request):
        u, db = request["user"], self.db
        kind = request.query.get("period", "today")
        if kind not in PERIODS:
            kind = "today"
        start, end, title = period(kind)
        mine = "" if is_admin(u) else " AND p.worker_id=?"
        mp = [] if is_admin(u) else [u["id"]]
        tot = await db.one("SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s, COALESCE(SUM(p.worker_share),0) sh "
                           "FROM payments p WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<?" + mine,
                           start, end, *mp)
        # график: по дням (до 62 дней) или по месяцам
        first = await db.one("SELECT MIN(reviewed_at) t FROM payments WHERE status='confirmed'")
        s_eff = max(start, (first["t"] or end) - 86400) if kind == "all" else start
        days = max(1, (end - s_eff + 86399) // 86400)
        rows = await db.all("SELECT p.amount, p.worker_share, p.reviewed_at FROM payments p WHERE p.status='confirmed' "
                            "AND p.reviewed_at>=? AND p.reviewed_at<?" + mine, s_eff, end, *mp)
        from datetime import datetime
        buckets: dict[str, list[int]] = {}
        if days <= 62:
            d0 = datetime.fromtimestamp(s_eff, TZ).date()
            for i in range(days):
                d = d0 + timedelta(days=i)
                buckets[d.strftime("%d.%m")] = [0, 0]
            fmt = "%d.%m"
        else:
            fmt = "%m.%Y"
        for r in rows:
            key = datetime.fromtimestamp(r["reviewed_at"], TZ).strftime(fmt)
            b = buckets.setdefault(key, [0, 0])
            b[0] += r["amount"]
            b[1] += r["worker_share"] or 0
        series = [{"label": k, "amount": v[0], "share": v[1]} for k, v in buckets.items()]
        result = {"title": title, "period": kind, "total": tot["s"], "count": tot["n"], "share": tot["sh"],
                  "rest": tot["s"] - tot["sh"], "series": series}
        if is_admin(u):
            result["workers"] = [dict(name=r["nick"] or r["username"] or "удалён", amount=r["s"], share=r["sh"], count=r["n"])
                                 for r in await db.all(
                "SELECT u.nick, u.username, COUNT(*) n, SUM(p.amount) s, COALESCE(SUM(p.worker_share),0) sh "
                "FROM payments p LEFT JOIN users u ON u.id=p.worker_id WHERE p.status='confirmed' "
                "AND p.reviewed_at>=? AND p.reviewed_at<? GROUP BY p.worker_id ORDER BY s DESC", start, end)]
            result["requisites"] = [dict(name=(f"…{r['iban'][-6:]} {r['holder']}" if r["iban"] else deleted_req_label(r["label"])),
                                         amount=r["s"], count=r["n"]) for r in await db.all(
                "SELECT r.iban, r.holder, p.requisite_label label, COUNT(*) n, SUM(p.amount) s FROM payments p "
                "LEFT JOIN requisites r ON r.id=p.requisite_id WHERE p.status='confirmed' AND p.reviewed_at>=? "
                "AND p.reviewed_at<? GROUP BY COALESCE(CAST(p.requisite_id AS TEXT), p.requisite_label) ORDER BY s DESC",
                start, end)]
            nc = await db.one("SELECT COUNT(*) n FROM clients WHERE created_at>=? AND created_at<?", start, end)
            result["new_clients"] = nc["n"]
        return web.json_response(result)


async def start_server(db: DB, bot: Bot, token: str, origin: str | None, port: int,
                       static_dir: str | None = None) -> web.AppRunner:
    api = Api(db, bot, token, origin, static_dir)
    runner = web.AppRunner(api.app(), access_log=None)  # без журнала запросов: в публичный лог не попадут данные
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    log.info("API приложения запущено")
    return runner
