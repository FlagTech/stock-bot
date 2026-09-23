import asyncio
import time

from .ai import Analyst, friendly_error
from .tool_worker import IsolatedMarket
from .platforms import PLATFORMS, DeliveryUncertain, Platforms
from .storage import Store
from .tunnel import Tunnel


class Runtime:
    def __init__(self, config, webhook_port=8768):
        self.config = config
        self.store = Store(config.root)
        self.analyst = Analyst(config, self.store, IsolatedMarket(config.root))
        self.platforms = Platforms(config, self.store)
        self.tunnel = Tunnel(config, webhook_port)
        self.workers = []
        self.apply_lock = asyncio.Lock()
        self.apply_task = None

    async def start(self):
        self.store.recover()
        self.store.purge(self.config.value.retention_days)
        self.workers = [asyncio.create_task(self.work()) for _ in range(2)]
        self.apply_task = asyncio.create_task(self.apply())

    async def apply(self, scope=PLATFORMS):
        async with self.apply_lock:
            await self.platforms.start(scope)
            if 'line' in scope:
                await self.tunnel.start()

    async def stop(self):
        if self.apply_task:
            await asyncio.gather(self.apply_task, return_exceptions=True)
        await self.platforms.stop()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        await self.tunnel.stop()
        await self.platforms.client.aclose()

    async def work(self):
        last_purge = time.time()
        while True:
            if self.apply_lock.locked():
                await asyncio.sleep(.3)
                continue
            if time.time() - last_purge > 3600:
                self.store.purge(self.config.value.retention_days)
                last_purge = time.time()
            job = self.store.claim()
            if not job:
                await asyncio.sleep(.3)
                continue
            delivering = False
            try:
                async with asyncio.timeout(self.config.value.timeout_seconds):
                    answer = await self.analyst.answer(job['session'], job['text'],
                        progress=lambda text, jid=job['id']: self.store.update(jid, progress=text))
                self.store.update(job['id'], result=answer)
                if job['platform'] != 'local':
                    delivering = True
                    self.store.update(job['id'], status='sending')
                    await self.platforms.send(job, answer)
                self.store.update(job['id'], status='done')
            except asyncio.CancelledError:
                # 保留 running/sending，下一次启动按中斷或不確定狀態處理。
                raise
            except DeliveryUncertain:
                self.store.update(job['id'], status='uncertain', error='傳送結果不確定，請先查看聊天紀錄；系統不會自動重送。')
            except Exception as exc:
                error = friendly_error(exc)
                self.store.update(job['id'], error=error)
                if job['platform'] != 'local' and not delivering:
                    try:
                        self.store.update(job['id'], status='sending')
                        await self.platforms.send(job, error)
                    except Exception:
                        self.store.update(job['id'], error=error + '（錯誤通知亦未能傳送。）')
                self.store.update(job['id'], status='failed')

    def status(self):
        return {'telegram': self.platforms.telegram_state, 'line': self.platforms.line_state,
                'line_last_event': self.store.meta('line_last_event'),
                'telegram_last_event': self.store.meta('telegram_last_event'),
                'line_notice_error': self.store.meta('line_notice_error'),
                'tunnel': self.tunnel.status(), 'applying': self.apply_lock.locked()}
