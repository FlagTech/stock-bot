import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from stock_bot.platforms import DeliveryUncertain, Platforms, chunks


def test_chunking_preserves_emoji_and_all_text():
    text = ('台積電😀' * 1700) + '\nend'
    parts = chunks(text)
    assert ''.join(parts) == text
    assert all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in parts)


async def test_line_retry_uses_same_key(config, runtime, monkeypatch):
    seen = []
    def handle(request):
        seen.append(request.headers.get('x-line-retry-key'))
        if len(seen) == 1:
            return httpx.Response(500)
        return httpx.Response(409, headers={'x-line-accepted-request-id': 'accepted'})
    monkeypatch.setattr('stock_bot.platforms.asyncio.sleep', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        platform = Platforms(config, runtime.store, client)
        await platform.line('message/push', {'to': 'test'}, 'stable-key')
    assert seen == ['stable-key', 'stable-key']


async def test_telegram_send_timeout_is_uncertain(config, runtime):
    def handle(request):
        raise httpx.ReadTimeout('sensitive URL must not escape')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        platform = Platforms(config, runtime.store, client)
        with pytest.raises(DeliveryUncertain):
            await platform.telegram('sendMessage', {'text': 'test'})


async def test_telegram_webhook_conflict(config, runtime):
    config.save(config.value.model_dump(), {'telegram_token': 'test-token'})
    def handle(request):
        return httpx.Response(200, json={'ok': True, 'result': {'url': 'https://old.example'} if 'getWebhookInfo' in str(request.url) else {'username':'sample','first_name':'Test'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        platform = Platforms(config, runtime.store, client)
        with pytest.raises(ValueError, match='已設定 Webhook'):
            await platform.test('telegram')


async def test_poll_persists_before_confirmation(config, runtime):
    config.save(config.value.model_dump(), {'telegram_token': 'test-token'})
    seen = []
    async def fake(method, payload=None, timeout=20):
        seen.append(payload['offset'])
        if len(seen) == 1:
            return [{'update_id': 10, 'message': {'chat': {'id': 99, 'type': 'private'}, 'text': '/help'}}]
        assert len(runtime.store.jobs()) == 1
        raise asyncio.CancelledError()
    runtime.platforms.telegram = fake
    with pytest.raises(asyncio.CancelledError):
        await runtime.platforms.poll()
    assert seen == [0, 11]


async def test_worker_help_without_credentials(runtime):
    jid, _ = runtime.store.enqueue('local', 'local:a', '', '/help')
    task = asyncio.create_task(runtime.work())
    try:
        for _ in range(100):
            if runtime.store.jobs()[0]['status'] == 'done':
                break
            await asyncio.sleep(.01)
        job = runtime.store.jobs()[0]
        assert job['id'] == jid and job['status'] == 'done'
        assert 'Stock Bot' in job['result']
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
