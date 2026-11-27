import os
from dataclasses import dataclass


@dataclass
class Config:
    token: str
    owner_id: int
    db_path: str
    db_password: str | None
    data_repo: str | None
    gh_token: str | None
    data_branch: str
    run_seconds: int
    save_interval: int


def load_config() -> Config:
    token = os.environ.get("BOT_TOKEN", "").strip()
    owner = os.environ.get("OWNER_ID", "").strip()
    if not token or not owner.isdigit():
        raise SystemExit("Не заданы BOT_TOKEN и/или OWNER_ID")
    db_path = os.environ.get("DB_PATH", "data/crm.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    cfg = Config(
        token=token,
        owner_id=int(owner),
        db_path=db_path,
        db_password=os.environ.get("DB_PASSWORD") or None,
        data_repo=os.environ.get("DATA_REPO") or None,
        gh_token=os.environ.get("GITHUB_TOKEN") or None,
        data_branch=os.environ.get("DATA_BRANCH", "bot-data"),
        run_seconds=int(os.environ.get("RUN_SECONDS", "0")),
        save_interval=int(os.environ.get("SAVE_INTERVAL", "60")),
    )
    if cfg.data_repo and cfg.gh_token and not cfg.db_password:
        raise SystemExit("Для хранения данных в репозитории нужен DB_PASSWORD")
    return cfg
