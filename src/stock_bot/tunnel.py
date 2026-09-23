import asyncio


class Tunnel:
    def __init__(self, config, port):
        self.config, self.port = config, port
        self.url = ''
        self.state = '尚未啟用'
        self.ngrok_config = None

    async def start(self):
        await self.stop()
        if not self.config.value.line_enabled or not self.config.value.ngrok_enabled:
            return
        if not self.config.secret('ngrok_token'):
            self.state = '缺少 ngrok authtoken'
            return
        def connect():
            from pyngrok import conf, ngrok
            # 專案專用路徑，停止時不影響其他 ngrok 程序；authtoken 不寫入一般設定。
            self.ngrok_config = conf.PyngrokConfig(
                ngrok_path=str(self.config.root / 'ngrok' / ('ngrok.exe' if __import__('os').name == 'nt' else 'ngrok')),
                config_path=str(self.config.root / 'ngrok.yml'),
                auth_token=self.config.secret('ngrok_token'), startup_timeout=20,
                monitor_thread=True)
            return ngrok.connect(addr=f'http://127.0.0.1:{self.port}', proto='http',
                                 bind_tls=True, pyngrok_config=self.ngrok_config).public_url
        self.state = '啟動中（首次需下載 ngrok）'
        try:
            self.url = await asyncio.to_thread(connect)
            self.state = '通道已連線'
        except Exception:
            self.state = '通道啟動失敗，請檢查 authtoken、網路與 ngrok 帳號額度。'
            await self._kill()

    async def _kill(self):
        if self.ngrok_config:
            from pyngrok import ngrok
            await asyncio.to_thread(ngrok.kill, self.ngrok_config)
            self.ngrok_config = None

    async def stop(self):
        await self._kill()
        self.url = ''
        self.state = '尚未啟用'

    def status(self):
        if self.ngrok_config and self.url:
            from pyngrok import process
            if not process.is_process_running(self.ngrok_config.ngrok_path):
                self.url = ''
                self.state = '通道已中斷，請按 LINE 區塊的「重新連線」。'
        return {'state': self.state, 'url': self.url + '/line/webhook' if self.url else ''}
