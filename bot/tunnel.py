"""Бесплатный туннель Cloudflare: даёт API приложения публичный HTTPS-адрес.

Адрес меняется при каждом запуске — бот сам сообщает его приложению
(через параметр в ссылке и файл api.json в ветке с данными).
Если туннель перестал отвечать, cloudflared перезапускается.
"""
import asyncio
import logging
import re

log = logging.getLogger(__name__)
# имена быстрых туннелей — слова через дефис; служебный api.trycloudflare.com не подходит
URL_RE = re.compile(rb"https://(?!api\.)[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")


class Tunnel:
    def __init__(self, binary: str, port: int, on_url):
        self.binary, self.port, self.on_url = binary, port, on_url
        self.proc: asyncio.subprocess.Process | None = None
        self.url: str | None = None

    async def _watch(self) -> None:
        """Раз в минуту проверяем туннель снаружи; 3 неудачи подряд — перезапуск cloudflared."""
        import aiohttp
        fails = 0
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            while self.proc and self.proc.returncode is None:
                await asyncio.sleep(60)
                if not self.url:
                    continue
                try:
                    async with s.get(self.url + "/api/health") as r:
                        fails = 0 if r.status == 200 else fails + 1
                except Exception:
                    fails += 1
                if fails >= 3:
                    log.warning("Туннель не отвечает — перезапуск")
                    self.proc.kill()
                    return

    async def run(self) -> None:
        backoff = 0
        while True:
            watch = None
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    self.binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                watch = asyncio.create_task(self._watch())
                async for line in self.proc.stderr:
                    m = URL_RE.search(line)
                    if m and m.group().decode() != self.url:
                        self.url = m.group().decode()
                        backoff = 0
                        log.info("Туннель приложения готов")
                        try:
                            await self.on_url(self.url)
                        except Exception as e:
                            log.warning("Не удалось применить адрес туннеля: %s", type(e).__name__)
                            self.url = None
                await self.proc.wait()
                log.warning("Туннель остановился, перезапуск")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Туннель не запустился: %s", type(e).__name__)
            finally:
                if watch:
                    watch.cancel()
            self.url = None
            await asyncio.sleep(min(300, 20 * 2 ** backoff))
            backoff = min(backoff + 1, 4)

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
