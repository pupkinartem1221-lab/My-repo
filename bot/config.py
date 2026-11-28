import os
from dataclasses import dataclass


@dataclass
class Config:
    token: str
    owner_id: int
    db_path: str
    db_password: str | None
    db_password_old: str | None
    data_repo: str | None
    gh_token: str | None
    data_branch: str
    init_db: bool
    run_seconds: int
    save_interval: int
    pages_url: str | None
    cloudflared: str | None
    api_port: int


def _int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} должен быть целым числом")
    if value < minimum:
        raise SystemExit(f"{name} должен быть не меньше {minimum}")
    return value


def load_config() -> Config:
    token = os.environ.get("BOT_TOKEN", "").strip()
    owner = os.environ.get("OWNER_ID", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN")
    if not (owner.isascii() and owner.isdecimal()):
        raise SystemExit("OWNER_ID должен состоять только из цифр")
    db_path = os.environ.get("DB_PATH", "data/crm.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    cfg = Config(
        token=token,
        owner_id=int(owner),
        db_path=db_path,
        db_password=os.environ.get("DB_PASSWORD") or None,
        db_password_old=os.environ.get("DB_PASSWORD_OLD") or None,
        data_repo=os.environ.get("DATA_REPO") or None,
        gh_token=os.environ.get("GITHUB_TOKEN") or None,
        data_branch=os.environ.get("DATA_BRANCH", "bot-data"),
        init_db=os.environ.get("INIT_DB", "").strip().lower() in ("1", "true", "yes"),
        run_seconds=_int("RUN_SECONDS", 0, 0),
        save_interval=_int("SAVE_INTERVAL", 60, 10),
        pages_url=(os.environ.get("PAGES_URL") or "").strip() or None,
        cloudflared=(os.environ.get("CLOUDFLARED") or "").strip() or None,
        api_port=_int("API_PORT", 8080, 1024),
    )
    if cfg.pages_url and not cfg.pages_url.startswith("https://"):
        raise SystemExit("PAGES_URL должен начинаться с https://")
    if cfg.data_repo:
        if not cfg.gh_token:
            raise SystemExit("DATA_REPO задан, но нет GITHUB_TOKEN — данные не сохранятся")
        if not cfg.db_password:
            raise SystemExit("Для хранения данных в репозитории нужен DB_PASSWORD")
        if len(cfg.db_password) < 24:
            raise SystemExit(
                "DB_PASSWORD слишком короткий: нужно не меньше 24 случайных символов. "
                "Сгенерируйте: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
    return cfg
