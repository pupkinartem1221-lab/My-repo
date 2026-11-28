"""Сохранение базы в отдельную ветку репозитория в зашифрованном виде.

Файл шифруется паролем из секрета DB_PASSWORD (PBKDF2-SHA256 + Fernet).
Ветка всегда содержит один коммит. Запись идёт через --force-with-lease:
если ветку изменил кто-то ещё (второй экземпляр бота), запись отклоняется
и бот останавливается, а не затирает чужие данные.
"""
import base64
import logging
import os
import subprocess
import tempfile
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = logging.getLogger(__name__)

MAGIC = b"CRMDB1"
FILE_NAME = "crm.db.enc"


class LeaseLost(RuntimeError):
    """Ветку с данными изменил кто-то другой."""


def _derive(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_derive(password, salt)).encrypt(data)


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("Неизвестный формат файла данных")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    return Fernet(_derive(password, salt)).decrypt(blob[len(MAGIC) + 16:])


class DataSync:
    def __init__(self, repo: str | None, token: str | None, branch: str, password: str | None,
                 old_password: str | None = None, init_db: bool = False):
        self.repo = repo
        self.token = token
        self.branch = branch
        self.password = password
        self.old_password = old_password
        self.init_db = init_db
        self.remote_sha = ""  # "" — ветки ещё нет
        self.extra_files: dict[str, str] = {}  # открытые файлы рядом с базой (например, api.json)

    @property
    def enabled(self) -> bool:
        return bool(self.repo and self.token and self.password)

    @property
    def _url(self) -> str:
        return f"https://github.com/{self.repo}.git"

    def _env(self) -> dict:
        # Токен передаётся заголовком через окружение — его нет ни в URL, ни в аргументах процесса.
        basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        return {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }

    def _git(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        env = self._env()
        try:
            # start_new_session: сигнал отмены из GitHub не должен убить git посреди сохранения
            res = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                                 text=True, timeout=90, start_new_session=True)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"git {args[0]}: превышено время ожидания") from None
        if res.returncode != 0:
            msg = res.stderr or res.stdout
            for secret in (self.token, env["GIT_CONFIG_VALUE_0"].split()[-1]):
                if secret:
                    msg = msg.replace(secret, "***")
            if "stale info" in msg or "fetch first" in msg or "non-fast-forward" in msg:
                raise LeaseLost(msg.strip())
            raise RuntimeError(f"git {args[0]} failed: {msg.strip()}")
        return res

    def _decrypt(self, blob: bytes) -> bytes:
        for pw in (self.password, self.old_password):
            if not pw:
                continue
            try:
                return decrypt(blob, pw)
            except InvalidToken:
                continue
        raise SystemExit("Не удалось расшифровать базу: неверный DB_PASSWORD")

    def load(self, db_path: str) -> bool:
        """Скачать и расшифровать базу. False — создана новая база (только при INIT_DB)."""
        if not self.enabled:
            return False
        last_error = None
        for attempt in range(5):
            try:
                heads = self._git("ls-remote", "--heads", self._url, self.branch).stdout.strip()
                if not heads:
                    if not self.init_db:
                        raise SystemExit(
                            f"Ветка {self.branch} с данными не найдена. Если это первый запуск, "
                            "запустите workflow вручную с галочкой «Создать новую базу».")
                    log.warning("Ветка с данными не найдена — создаётся новая база (INIT_DB)")
                    self.remote_sha = ""
                    return False
                self.remote_sha = heads.split()[0]
                with tempfile.TemporaryDirectory() as d:
                    self._git("clone", "-q", "--depth", "1", "--single-branch",
                              "--branch", self.branch, self._url, d)
                    self.remote_sha = self._git("rev-parse", "HEAD", cwd=d).stdout.strip()
                    path = os.path.join(d, FILE_NAME)
                    if not os.path.exists(path):
                        raise SystemExit(f"В ветке {self.branch} нет {FILE_NAME} — запуск остановлен, "
                                         "чтобы не затереть данные")
                    with open(path, "rb") as f:
                        data = self._decrypt(f.read())
                fd = os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                log.info("База загружена")
                return True
            except RuntimeError as e:
                last_error = e
                log.warning("Не удалось загрузить базу (попытка %s): %s", attempt + 1, e)
                time.sleep(5 * (attempt + 1))
        # Нельзя стартовать с пустой базой — иначе она перезапишет настоящие данные.
        raise SystemExit(f"Не удалось загрузить базу: {last_error}")

    def save(self, snapshot_path: str) -> None:
        with open(snapshot_path, "rb") as f:
            blob = encrypt(f.read(), self.password)
        with tempfile.TemporaryDirectory() as d:
            self._git("init", "-q", cwd=d)
            self._git("checkout", "-q", "-b", self.branch, cwd=d)
            with open(os.path.join(d, FILE_NAME), "wb") as f:
                f.write(blob)
            with open(os.path.join(d, "README.md"), "w") as f:
                f.write("Зашифрованные данные CRM-бота. Не редактировать и не удалять.\n")
            for name, content in dict(self.extra_files).items():
                with open(os.path.join(d, name), "w") as f:
                    f.write(content)
            self._git("add", ".", cwd=d)
            self._git("-c", "user.name=crm-bot", "-c", "user.email=crm-bot@users.noreply.github.com",
                      "commit", "-q", "-m", "data", cwd=d)
            self._git("push", "-q", f"--force-with-lease=refs/heads/{self.branch}:{self.remote_sha}",
                      self._url, f"HEAD:refs/heads/{self.branch}", cwd=d)
            self.remote_sha = self._git("rev-parse", "HEAD", cwd=d).stdout.strip()
