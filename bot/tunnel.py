"""Бесплатный туннель Cloudflare: даёт API приложения публичный HTTPS-адрес.

Адрес меняется при каждом запуске — бот сам сообщает его приложению
(через параметр в ссылке и файл api.json в ветке с данными).
"""
import asyncio
import logging
import re

log = logging.getLogger(__name__)
URL_RE = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    def __init__(self, binary: str, port: int, on_url):
        self.binary, self.port, self.on_url = binary, port, on_url
        self.proc: asyncio.subprocess.Process | None = None
        self.url: str | None = None

    async def run(self) -> None:
        while True:
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    self.binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                async for line in self.proc.stderr:
                    m = URL_RE.search(line)
                    if m and m.group().decode() != self.url:
                        self.url = m.group().decode()
                        log.info("Туннель приложения готов")
                        try:
                            await self.on_url(self.url)
                        except Exception as e:
                            log.warning("Не удалось применить адрес туннеля: %s", type(e).__name__)
                await self.proc.wait()
                log.warning("Туннель остановился, перезапуск через 20 с")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Туннель не запустился: %s", type(e).__name__)
            await asyncio.sleep(20)

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
