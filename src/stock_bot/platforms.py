"""平台 API 保持獨立；此模組不負責 AI 推論。"""
import asyncio
import base64
import hashlib
import hmac
import time
from uuid import NAMESPACE_URL, uuid5

import httpx

PLATFORMS = ('telegram', 'line')
# 各平台在設定檔與憑證庫中的欄位；變更時只需重啟該平台。
PLATFORM_FIELDS = {'telegram': ('telegram_enabled',), 'line': ('line_enabled', 'ngrok_enabled')}
PLATFORM_SECRETS = {'telegram': ('telegram_token',), 'line': ('line_secret', 'line_token', 'ngrok_token')}


def valid_signature(body: bytes, signature: str, secret: str):
    expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return bool(secret) and hmac.compare_digest(expected, signature)


def chunks(text, limit=3500):
    """以 UTF-16 code units 保守分段，避免 emoji 讓 LINE 長度超限。"""
    result, part, units = [], [], 0
    for char in text:
        size = len(char.encode('utf-16-le')) // 2
        if units + size > limit:
            result.append(''.join(part))
            part, units = [], 0
        part.append(char)
        units += size
    if part:
        result.append(''.join(part))
    return result or ['（沒有文字回覆）']


class DeliveryUncertain(Exception):
    pass


class Platforms:
    def __init__(self, config, store, client=None):
        self.config, self.store = config, store
        self.client = client or httpx.AsyncClient(timeout=20)
        self.telegram_state = '尚未啟用'
        self.line_state = '尚未啟用'
        self.bot_name = ''
        self.poll_task = None

    async def line(self, path, payload=None, retry_key=None):
        headers = {'Authorization': 'Bearer ' + self.config.secret('line_token')}
        if retry_key:
            headers['X-Line-Retry-Key'] = retry_key
        url = 'https://api.line.me/v2/bot/' + path
        for attempt in range(3):
            try:
                r = await self.client.request('GET' if payload is None else 'POST', url, headers=headers, json=payload)
                if r.status_code == 409 and retry_key and r.headers.get('x-line-accepted-request-id'):
                    return {}
                if r.status_code == 429 or r.status_code >= 500:
                    if not retry_key or attempt == 2:
                        if retry_key and r.status_code >= 500:
                            raise DeliveryUncertain()
                        raise ValueError('LINE 暫時無法傳送，請檢查訊息額度或稍後再試。')
                    await asyncio.sleep(2 ** attempt)
                    continue
                if r.is_error:
                    raise ValueError('LINE API 拒絕請求，請檢查權杖、好友狀態與訊息額度。')
                return r.json()
            except httpx.TransportError as exc:
                if not retry_key or attempt == 2:
                    raise DeliveryUncertain() from exc
                await asyncio.sleep(2 ** attempt)

    async def telegram(self, method, payload=None, timeout=20):
        token = self.config.secret('telegram_token')
        try:
            r = await self.client.post(f'https://api.telegram.org/bot{token}/{method}', json=payload or {}, timeout=timeout)
        except httpx.TransportError as exc:
            if method == 'sendMessage':
                raise DeliveryUncertain() from exc
            raise ValueError('Telegram 連線失敗，請檢查網路。') from exc
        if r.status_code == 409:
            raise ValueError('Telegram 接收衝突：請停止其他機器人程序，或解除既有 Webhook。')
        if r.status_code == 429:
            raise ValueError('Telegram 請求過於頻繁，請稍後再試。')
        if r.status_code >= 500 and method == 'sendMessage':
            raise DeliveryUncertain()
        if r.is_error:
            raise ValueError('Telegram API 拒絕請求，請檢查 Bot token 或是否封鎖機器人。')
        data = r.json()
        if not data.get('ok'):
            raise ValueError('Telegram 未接受請求，請檢查 Bot 設定。')
        return data.get('result')

    async def test(self, platform):
        if platform == 'line':
            if not self.config.secret('line_token') or not self.config.secret('line_secret'):
                raise ValueError('請先儲存 LINE 的兩項金鑰。')
            info = await self.line('info')
            self.line_state = '權杖測試成功，等待 Webhook'
            return f"LINE 權杖有效：{info.get('displayName', 'Bot')}。簽章需用實際 Webhook 驗證。"
        if not self.config.secret('telegram_token'):
            raise ValueError('請先儲存 Telegram Bot token。')
        info = await self.telegram('getMe')
        self.bot_name = info.get('first_name', '')
        webhook = await self.telegram('getWebhookInfo')
        if webhook.get('url'):
            raise ValueError('此 Bot 已設定 Webhook。確認停用原服務後，按「解除舊 Webhook」再啟動。')
        return f'Telegram 連線成功：{self.bot_name}'

    async def start(self, scope=PLATFORMS):
        await self.stop(scope)
        if 'line' in scope and self.config.value.line_enabled:
            self.line_state = '等待 Webhook' if self.config.secret('line_secret') and self.config.secret('line_token') else '缺少 LINE 金鑰'
        if 'telegram' in scope and self.config.value.telegram_enabled:
            try:
                await self.test('telegram')
                self.poll_task = asyncio.create_task(self.poll())
                self.telegram_state = '接收中'
            except Exception as exc:
                from .ai import friendly_error
                self.telegram_state = friendly_error(exc)

    async def stop(self, scope=PLATFORMS):
        if 'telegram' in scope:
            if self.poll_task:
                self.poll_task.cancel()
                await asyncio.gather(self.poll_task, return_exceptions=True)
                self.poll_task = None
            self.telegram_state = '尚未啟用'
            self.bot_name = ''
        if 'line' in scope:
            self.line_state = '尚未啟用'

    async def poll(self):
        fingerprint = hashlib.sha256(self.config.secret('telegram_token').encode()).hexdigest()[:16]
        offset_key = 'telegram_offset_' + fingerprint
        offset = self.store.meta(offset_key) or 0
        while True:
            try:
                updates = await self.telegram('getUpdates', {'offset': offset, 'timeout': 25,
                                               'allowed_updates': ['message'], 'limit': 25}, timeout=35)
                self.telegram_state = '接收中'
                for update in updates:
                    msg = update.get('message', {})
                    # 第一版只處理私人文字訊息，避免群組對話與通知污染。
                    if msg.get('chat', {}).get('type') == 'private' and msg.get('text'):
                        uid = str(msg['chat']['id'])
                        text = msg['text']
                        if 0 < len(text.strip()) <= 4000:
                            self.store.enqueue('telegram', f'telegram:{fingerprint}:{uid}', uid, text,
                                               f'tg:{fingerprint}:{update["update_id"]}')
                            self.store.meta('telegram_last_event', time.time())
                    # 確認前先持久保存工作和 offset，重送依 event id 去重。
                    offset = update['update_id'] + 1
                    self.store.meta(offset_key, offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                from .ai import friendly_error
                self.telegram_state = friendly_error(exc)
                await asyncio.sleep(8)

    async def acknowledge(self, token):
        try:
            await self.line('message/reply', {'replyToken': token,
                'messages': [{'type': 'text', 'text': '已收到，正在處理你的問題。完成後會傳回結果。'}]})
        except Exception:
            # 通知失敗不能取消已持久保存的工作，也不輸出含金鑰的 API 例外。
            self.store.meta('line_notice_error', '處理中通知未成功；分析工作仍會繼續。')

    async def send(self, job, answer):
        parts = chunks(answer)
        for index, part in enumerate(parts):
            if index < job['sent']:
                continue
            if job['platform'] == 'line':
                key = str(uuid5(NAMESPACE_URL, f'stock-bot:{job["id"]}:{index}'))
                await self.line('message/push', {'to': job['target'], 'messages': [{'type': 'text', 'text': part}]}, key)
            else:
                await self.telegram('sendMessage', {'chat_id': job['target'], 'text': part,
                                                     'link_preview_options': {'is_disabled': True}})
                await asyncio.sleep(1.1)
            self.store.update(job['id'], sent=index + 1)
