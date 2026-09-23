import pytest

from stock_bot.config import Config
from stock_bot.runtime import Runtime


class MemoryVault:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[service, name] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


@pytest.fixture
def config(tmp_path, monkeypatch):
    from stock_bot.config import ENV
    for name in ENV.values():
        monkeypatch.delenv(name, raising=False)
    return Config(tmp_path, MemoryVault())


@pytest.fixture
def runtime(config):
    return Runtime(config)


class FunctionCall:
    type = 'function_call'

    def __init__(self, name, arguments, call_id='call'):
        self.name, self.arguments, self.call_id = name, arguments, call_id

    def model_dump(self, **kwargs):
        return {'type': 'function_call', 'call_id': self.call_id, 'name': self.name, 'arguments': self.arguments}


@pytest.fixture
def responses_api(monkeypatch):
    """以假 Responses API 取代 OpenAI 用戶端；install(create) 後回傳用戶端供斷言。"""
    from types import SimpleNamespace

    def install(create):
        client = SimpleNamespace(responses=SimpleNamespace(create=create))

        class FakeClient:
            responses = client.responses
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False

        monkeypatch.setattr('stock_bot.ai.AsyncOpenAI', lambda **kwargs: FakeClient())
        return client

    return SimpleNamespace(
        install=install,
        tool=lambda name, arguments: SimpleNamespace(output=[FunctionCall(name, arguments)], output_text=''),
        text=lambda text, output=(): SimpleNamespace(output=list(output), output_text=text))
