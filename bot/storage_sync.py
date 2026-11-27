"""Сохранение базы в отдельную ветку репозитория в зашифрованном виде.

Репозиторий публичный, поэтому файл шифруется паролем из секрета DB_PASSWORD.
Ветка всегда содержит один коммит (force-push), история не разрастается.
"""
import base64
import logging
import os
import subprocess
import tempfile
import time

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = logging.getLogger(__name__)

MAGIC = b"CRMDB1"
FILE_NAME = "crm.db.enc"


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
    def __init__(self, repo: str | None, token: str | None, branch: str, password: str | None):
        self.repo = repo
        self.token = token
        self.branch = branch
        self.password = password

    @property
    def enabled(self) -> bool:
        return bool(self.repo and self.token and self.password)

    @property
    def _url(self) -> str:
        return f"https://x-access-token:{self.token}@github.com/{self.repo}.git"

    def _git(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            msg = (res.stderr or res.stdout).replace(self.token or "\0", "***")
            raise RuntimeError(f"git {args[0]} failed: {msg.strip()}")
        return res

    def load(self, db_path: str) -> bool:
        """Скачать и расшифровать базу. False — данных ещё нет (первый запуск)."""
        if not self.enabled:
            return False
        last_error = None
        for attempt in range(5):
            try:
                heads = self._git("ls-remote", "--heads", self._url, self.branch).stdout.strip()
                if not heads:
                    log.info("Ветка с данными не найдена — создаётся новая база")
                    return False
                with tempfile.TemporaryDirectory() as d:
                    self._git("clone", "-q", "--depth", "1", "--single-branch",
                              "--branch", self.branch, self._url, d)
                    path = os.path.join(d, FILE_NAME)
                    if not os.path.exists(path):
                        return False
                    with open(path, "rb") as f:
                        data = decrypt(f.read(), self.password)
                with open(db_path, "wb") as f:
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
                f.write("Зашифрованные данные CRM-бота. Не редактировать вручную.\n")
            self._git("add", ".", cwd=d)
            self._git("-c", "user.name=crm-bot", "-c", "user.email=crm-bot@users.noreply.github.com",
                      "commit", "-q", "-m", "data", cwd=d)
            self._git("push", "-q", "-f", self._url, f"HEAD:refs/heads/{self.branch}", cwd=d)
