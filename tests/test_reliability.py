import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stock_bot.api import make_admin
from stock_bot.market import Market
from stock_bot.platforms import DeliveryUncertain, Platforms
from stock_bot.tool_worker import IsolatedMarket


async def test_kills_timed_out_data_process(tmp_path, monkeypatch):
    class Process:
        returncode = None
        killed = False
        async def communicate(self, payload):
            await asyncio.sleep(60)
        def kill(self): self.killed = True
        async def wait(self): self.returncode = -1
    process = Process()
    create = AsyncMock(return_value=process)
    monkeypatch.setattr('stock_bot.tool_worker.asyncio.create_subprocess_exec', create)
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-pass')
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(IsolatedMarket(tmp_path).call('stock_price', {'stock_id':'2330'}), .03)
    assert process.killed
    assert 'OPENAI_API_KEY' not in create.await_args.kwargs['env']


def test_settings_cannot_change_during_jobs(runtime):
    runtime.store.enqueue('local', 'local', '', 'question')
    with TestClient(make_admin(runtime, manage_lifecycle=False), base_url='http://127.0.0.1:8767') as client:
        token = client.get('/api/bootstrap').json()['token']
        response = client.put('/api/settings', json={'values':runtime.config.value.model_dump(),'secrets':{}},
                              headers={'x-stock-bot-token':token})
        assert response.status_code == 400


def test_invalid_setting_does_not_disconnect(runtime):
    runtime.platforms.stop = AsyncMock()
    with TestClient(make_admin(runtime, manage_lifecycle=False), base_url='http://127.0.0.1:8767') as client:
        token = client.get('/api/bootstrap').json()['token']
        response = client.put('/api/settings', json={'values':{'timeout_seconds':0},'secrets':{}},
                              headers={'x-stock-bot-token':token})
        assert response.status_code == 400
        runtime.platforms.stop.assert_not_awaited()


def save_settings(runtime, body):
    runtime.platforms.stop = AsyncMock()
    runtime.tunnel.stop = AsyncMock()
    runtime.apply = AsyncMock()
    with TestClient(make_admin(runtime, manage_lifecycle=False), base_url='http://127.0.0.1:8767') as client:
        token = client.get('/api/bootstrap').json()['token']
        return client.put('/api/settings', json=body, headers={'x-stock-bot-token':token})


def test_platform_save_restarts_only_that_platform(runtime):
    response = save_settings(runtime, {'values':runtime.config.value.model_dump(),
                                       'secrets':{'telegram_token':''}, 'scope':'telegram'})
    assert response.status_code == 200
    runtime.platforms.stop.assert_awaited_once_with(('telegram',))
    runtime.tunnel.stop.assert_not_awaited()
    runtime.apply.assert_called_once_with(('telegram',))


def test_restart_follows_changed_settings(runtime):
    response = save_settings(runtime, {'values':{**runtime.config.value.model_dump(), 'model':'another-model'},
                                       'secrets':{'line_token':'new-token'}})
    assert response.status_code == 200
    runtime.platforms.stop.assert_awaited_once_with(('line',))
    runtime.tunnel.stop.assert_awaited_once()
    runtime.apply.assert_called_once_with(('line',))
    response = save_settings(runtime, {'values':{**runtime.config.value.model_dump(), 'model':'third-model'},
                                       'secrets':{}})
    assert response.status_code == 200
    runtime.platforms.stop.assert_not_awaited()
    runtime.apply.assert_not_called()


async def test_line_final_server_error_uncertain(config, runtime, monkeypatch):
    monkeypatch.setattr('stock_bot.platforms.asyncio.sleep', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as client:
        with pytest.raises(DeliveryUncertain):
            await Platforms(config, runtime.store, client).line('message/push', {}, 'same-key')


def test_stock_cache_survives_source_outage(tmp_path, monkeypatch):
    rows=[{'股號':'2330','股名':'台積電','市場別':'上市'},{'股號':'6488','股名':'環球晶','市場別':'上櫃'}]
    (tmp_path/'stocks.json').write_text(json.dumps({'updated':0,'rows':rows}), encoding='utf-8')
    def fail(*args, **kwargs): raise httpx.ConnectError('offline')
    market=Market(tmp_path)
    monkeypatch.setattr(market,'get_json',fail)
    assert market.catalog() == rows


def test_fundamental_gap_not_reported_as_quarter_growth(tmp_path, monkeypatch):
    from types import SimpleNamespace
    data=pd.DataFrame([[100.,150.],[2.,3.]],index=['Total Revenue','Basic EPS'],columns=pd.to_datetime(['2025-03-31','2025-09-30']))
    stock=SimpleNamespace(quarterly_financials=data,financials=pd.DataFrame(),balance_sheet=pd.DataFrame())
    monkeypatch.setattr('stock_bot.market.yf.Ticker',lambda _:stock)
    market=Market(tmp_path)
    monkeypatch.setattr(market,'resolve',lambda _:('2330.TW','台積電'))
    result=market.stock_fundamental('2330')
    assert result['季報']['EPS 季增率'] == {}
    assert result['季報']['毛利率'] == {}
