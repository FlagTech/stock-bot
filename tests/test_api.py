import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from stock_bot.api import make_admin, make_webhook


def test_admin_host_origin_and_csrf(runtime):
    with TestClient(make_admin(runtime, manage_lifecycle=False), base_url='http://127.0.0.1:8767') as client:
        assert client.get('/api/bootstrap', headers={'host': 'evil.example'}).status_code == 403
        assert client.get('/api/bootstrap', headers={'origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/chat', json={'text': 'hi'}).status_code == 403
        token = client.get('/api/bootstrap').json()['token']
        response = client.post('/api/chat', json={'text': '/help'}, headers={'x-stock-bot-token': token})
        assert response.status_code == 200
        assert len(runtime.store.jobs()) == 1


def test_settings_do_not_return_or_write_secrets(runtime):
    config = runtime.config
    config.save(config.value.model_dump(), {'openai_key': 'private-key-example'})
    assert 'private-key-example' not in json.dumps(config.public())
    assert 'private-key-example' not in (config.root / 'settings.json').read_text()
    assert config.secret('openai_key') == 'private-key-example'
    config.save(config.value.model_dump(), {'openai_key': ''})
    assert config.secret('openai_key') == 'private-key-example'
    config.save(config.value.model_dump(), {'openai_key': None})
    assert not config.secret('openai_key')


def test_webhook_signature_dedupe_and_private_only(runtime):
    runtime.config.save({**runtime.config.value.model_dump(), 'line_enabled': True}, {'line_secret': 'test-secret'})
    runtime.platforms.acknowledge = AsyncMock()
    body = json.dumps({'events': [{'type': 'message', 'webhookEventId': 'test-event', 'replyToken': 'reply',
        'source': {'type': 'user', 'userId': 'user'}, 'message': {'type': 'text', 'text': '台積電'}}]}, ensure_ascii=False).encode()
    signature = base64.b64encode(hmac.new(b'test-secret', body, hashlib.sha256).digest()).decode()
    with TestClient(make_webhook(runtime)) as client:
        assert client.post('/line/webhook', content=body).status_code == 401
        for _ in range(2):
            assert client.post('/line/webhook', content=body, headers={'x-line-signature': signature}).status_code == 200
        assert len(runtime.store.jobs()) == 1
        assert runtime.platforms.acknowledge.await_count == 1
        assert client.get('/api/settings').status_code == 404
        assert client.get('/api/bootstrap').status_code == 404
        changed = body + b' '
        assert client.post('/line/webhook', content=changed, headers={'x-line-signature': signature}).status_code == 401


def test_empty_verification_event(runtime):
    runtime.config.save({**runtime.config.value.model_dump(), 'line_enabled': True}, {'line_secret': 'secret'})
    body = b'{"events":[]}'
    signature = base64.b64encode(hmac.new(b'secret', body, hashlib.sha256).digest()).decode()
    with TestClient(make_webhook(runtime)) as client:
        assert client.post('/line/webhook', content=body, headers={'x-line-signature': signature}).status_code == 200
    assert not runtime.store.jobs()


def test_no_chat_identifiers_in_jobs(runtime):
    runtime.store.enqueue('line', 'secret-session', 'user-id', 'hello', 'evt')
    with TestClient(make_admin(runtime, manage_lifecycle=False), base_url='http://127.0.0.1:8767') as client:
        data = client.get('/api/jobs').json()[0]
        assert not {'session', 'event', 'target'} & data.keys()
