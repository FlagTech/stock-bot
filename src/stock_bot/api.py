import asyncio
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai import friendly_error
from .platforms import PLATFORM_FIELDS, PLATFORM_SECRETS, PLATFORMS, valid_signature

Platform = Literal['telegram', 'line']


class SettingsUpdate(BaseModel):
    values: dict
    secrets: dict[str, str | None] = Field(default_factory=dict)
    scope: Platform | None = None


def platforms_to_restart(body, current, updated):
    """指定的平台，加上欄位或金鑰有變動的平台；其他平台與通道維持連線。"""
    def secret_changed(name):
        return name in body.secrets and (body.secrets[name] is None or body.secrets[name].strip())
    return tuple(p for p in PLATFORMS if p == body.scope
                 or any(getattr(updated, f) != getattr(current, f) for f in PLATFORM_FIELDS[p])
                 or any(secret_changed(s) for s in PLATFORM_SECRETS[p]))


class ChatInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def make_admin(runtime, port=8767, manage_lifecycle=True):
    @asynccontextmanager
    async def lifespan(app):
        if manage_lifecycle:
            await runtime.start()
        yield
        if manage_lifecycle:
            await runtime.stop()

    app = FastAPI(title='Stock Bot 本機控制台', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    token = secrets.token_urlsafe(32)
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}

    @app.middleware('http')
    async def local_only(request, call_next):
        # Host 防 DNS rebinding；Origin 和自訂標頭保護本機修改操作。
        if request.headers.get('host') not in allowed_hosts:
            return JSONResponse({'detail': '控制台僅供本機存取。'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin not in {f'http://{h}' for h in allowed_hosts}:
            return JSONResponse({'detail': '拒絕跨網站請求。'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('x-stock-bot-token') != token:
                return JSONResponse({'detail': '頁面驗證已失效，請重新整理。'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail': friendly_error(exc)}, status_code=400)

    @app.get('/api/bootstrap')
    def bootstrap():
        return {'token': token, 'settings': runtime.config.public(), 'status': runtime.status()}

    @app.get('/api/status')
    def status():
        return runtime.status()

    @app.get('/api/settings')
    def settings():
        return runtime.config.public()

    @app.put('/api/settings')
    async def save(body: SettingsUpdate):
        # 變更前等待在途工作完成，避免換金鑰把舊工作的結果傳到新 Bot。
        if runtime.apply_lock.locked() or any(j['status'] in ('queued', 'running', 'sending') for j in runtime.store.jobs()):
            raise ValueError('仍有工作或平台設定正在執行，請完成後再儲存。')
        from .config import Settings
        updated = Settings.model_validate(body.values)
        scope = platforms_to_restart(body, runtime.config.value, updated)
        async with runtime.apply_lock:
            if scope:
                await runtime.platforms.stop(scope)
            if 'line' in scope:
                await runtime.tunnel.stop()
            try:
                runtime.config.save(body.values, body.secrets)
            except Exception:
                if scope:
                    runtime.apply_task = asyncio.create_task(runtime.apply(scope))
                raise
        if scope:
            runtime.apply_task = asyncio.create_task(runtime.apply(scope))
        return runtime.config.public()

    @app.post('/api/test/{platform}')
    async def test(platform: str):
        if platform not in ('openai', 'line', 'telegram'):
            raise HTTPException(404)
        try:
            message = await runtime.analyst.test() if platform == 'openai' else await runtime.platforms.test(platform)
            return {'message': message}
        except Exception as exc:
            return JSONResponse({'detail': friendly_error(exc)}, status_code=400)

    @app.post('/api/platforms/apply')
    async def apply(platform: Platform | None = None):
        if runtime.apply_lock.locked():
            raise ValueError('平台正在啟動，請稍候。')
        runtime.apply_task = asyncio.create_task(runtime.apply((platform,) if platform else PLATFORMS))
        return {'message': '正在重新連線。'}

    @app.post('/api/telegram/delete-webhook')
    async def remove_webhook():
        await runtime.platforms.telegram('deleteWebhook', {'drop_pending_updates': False})
        return {'message': '已解除舊 Webhook，保留未接收訊息。請重新連線。'}

    @app.get('/api/jobs')
    def jobs():
        # 控制台不需要暴露外部聊天室識別碼。
        return [{k: v for k, v in j.items() if k not in ('target', 'session', 'event')} for j in runtime.store.jobs()]

    @app.post('/api/chat')
    def chat(body: ChatInput):
        if runtime.apply_lock.locked():
            raise ValueError('平台設定正在套用，請稍候。')
        jid, _ = runtime.store.enqueue('local', 'local:default', '', body.text)
        return {'id': jid}

    @app.get('/api/chat')
    def history():
        return runtime.store.history('local:default', 20)

    @app.post('/api/chat/reset')
    def reset():
        jid, _ = runtime.store.enqueue('local', 'local:default', '', '/reset')
        return {'id': jid}

    @app.delete('/api/records')
    def purge():
        if any(j['status'] in ('queued','running','sending') for j in runtime.store.jobs()):
            raise ValueError('請等待所有工作完成再清除紀錄。')
        runtime.store.purge()
        return {'message': '已清除對話與工作紀錄。'}

    @app.get('/api/diagnostics')
    def diagnostics():
        import importlib.metadata
        return {'version': importlib.metadata.version('stock-bot'),
                'configured': runtime.config.public()['configured'],
                'platforms_enabled': {'line': runtime.config.value.line_enabled, 'telegram': runtime.config.value.telegram_enabled},
                'jobs': [{'status': j['status'], 'platform': j['platform']} for j in runtime.store.jobs()]}

    web = Path(__file__).parent / 'web'
    if web.exists():
        app.mount('/', StaticFiles(directory=web, html=True), name='web')
    return app


def make_webhook(runtime):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.post('/line/webhook')
    async def webhook(request: Request, background: BackgroundTasks):
        if not runtime.config.value.line_enabled or runtime.apply_lock.locked():
            raise HTTPException(503, 'LINE 尚未啟用')
        body = bytearray()
        async for piece in request.stream():
            body.extend(piece)
            if len(body) > 1024 * 1024:
                raise HTTPException(413)
        if not valid_signature(bytes(body), request.headers.get('x-line-signature', ''), runtime.config.secret('line_secret')):
            raise HTTPException(401, '簽章不符')
        try:
            payload = json.loads(body)
            events = payload['events']
            if not isinstance(events, list):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, 'Webhook 格式錯誤')
        fingerprint = hashlib.sha256(runtime.config.secret('line_secret').encode()).hexdigest()[:16]
        for event in events:
            if not isinstance(event, dict):
                continue
            source, msg = event.get('source', {}), event.get('message', {})
            if event.get('type') != 'message' or msg.get('type') != 'text' or source.get('type') != 'user':
                continue
            uid, eid, text = source.get('userId'), event.get('webhookEventId'), msg.get('text', '')
            if not uid or not eid or not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
                continue
            try:
                _, fresh = runtime.store.enqueue('line', f'line:{fingerprint}:{uid}', uid, text, f'line:{fingerprint}:{eid}')
            except ValueError:
                raise HTTPException(503, '佇列忙碌，請稍後重送')
            if fresh and event.get('replyToken'):
                background.add_task(runtime.platforms.acknowledge, event['replyToken'])
            runtime.store.meta('line_last_event', time.time())
        runtime.platforms.line_state = 'Webhook 已驗證' if not events else '已收到 Webhook'
        return {'ok': True}

    return app
