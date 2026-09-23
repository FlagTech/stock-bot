from types import SimpleNamespace
from unittest.mock import AsyncMock
import datetime as dt

import pandas as pd
import pytest
from pydantic import ValidationError

from stock_bot.ai import Analyst, PriceArgs, friendly_error
from stock_bot.market import Market, TZ, series_dict


def test_validation_bounds():
    with pytest.raises(ValidationError):
        PriceArgs(stock_id='2330', days=99999)
    with pytest.raises(ValidationError):
        PriceArgs(stock_id='../../secret')
    assert PriceArgs(stock_id='006208').days == 15


def test_finite_series_only():
    s = pd.Series([1, float('inf'), float('nan')], index=pd.date_range('2026-01-01', periods=3))
    assert series_dict(s) == {'2026-01-01': 1.0}


def test_price_reads_named_columns_and_raw_close_return(tmp_path, monkeypatch):
    market = Market(tmp_path)
    monkeypatch.setattr(market, 'resolve', lambda s: ('2330.TW', '台積電'))
    # 欄位順序不同且含額外欄位，不應影響結果。
    today = dt.datetime.now(TZ).date()
    frame = pd.DataFrame({'Volume':[10,20], 'Close':[100.,50.], 'Extra':[0,0], 'Adj Close':[50.,50.]},
                         index=pd.to_datetime([today-dt.timedelta(days=1), today]))
    monkeypatch.setattr('stock_bot.market.yf.download', lambda *a, **k: frame)
    data = market.stock_price('2330')
    assert data['收盤價'][str(today)] == 50
    assert data['期間報酬'] == '-50.00%'
    assert data['每日報酬'][str(today)] == '-50.00%'
    assert '調整後每日報酬' not in data


def test_partial_report_keeps_working_sources(tmp_path, monkeypatch):
    market = Market(tmp_path)
    monkeypatch.setattr(market, 'stock_price', lambda s: {'收盤價': 100})
    monkeypatch.setattr(market, 'stock_fundamental', lambda s: {})
    def fail(s):
        raise RuntimeError('network down')
    monkeypatch.setattr(market, 'stock_news', fail)
    data = market.stock_trend_report('2330')
    assert data['stock_price']['收盤價'] == 100
    assert '錯誤' in data['stock_news']


async def test_ai_tool_flow_and_conversation(runtime, responses_api):
    config = runtime.config
    config.save({**config.value.model_dump(), 'model': 'test-model'}, {'openai_key': 'fake'})
    create = AsyncMock(side_effect=[responses_api.tool('stock_price', '{"stock_id":"2330","days":30}'),
                                    responses_api.text('根據資料，收盤價為 100 元。')])
    responses_api.install(create)
    market = SimpleNamespace(call=AsyncMock(return_value={'收盤價':100}))
    steps = []
    answer = await Analyst(config, runtime.store, market).answer('local:a', '台積電股價', progress=steps.append)
    assert '100' in answer
    assert steps == ['正在呼叫 股價查詢 工具', '']
    assert market.call.await_args.args[0] == 'stock_price'
    first, second = (call.kwargs for call in create.await_args_list)
    assert first['store'] is False and 'reasoning.encrypted_content' in first['include']
    assert first['instructions'].startswith('你是')
    # 同一份輸入清單逐輪累積：使用者問題、模型工具呼叫、對應 call_id 的工具結果。
    user, call, output = second['input']
    assert user == {'role': 'user', 'content': '台積電股價'}
    assert call['type'] == 'function_call'
    assert output['type'] == 'function_call_output' and output['call_id'] == call['call_id']
    assert len(runtime.store.history('local:a', 5)) == 2
    assert not runtime.store.history('local:b', 5)


def test_provider_errors_do_not_leak_tokens():
    assert 'secret' not in friendly_error(RuntimeError('https://api/bot-secret'))


async def test_context_overflow_trims_history_only(runtime, responses_api):
    import httpx
    from openai import BadRequestError

    config = runtime.config
    config.save({'model': 'test'}, {'openai_key': 'fake'})
    for i in range(25):
        runtime.store.remember('long', f'q{i}', f'a{i}')
    snapshots = []

    async def create(**kwargs):
        snapshots.append(list(kwargs['input']))
        if len(snapshots) == 1:
            raise BadRequestError('too long', response=httpx.Response(400, request=httpx.Request('POST', 'https://example.com')),
                                  body={'code': 'context_length_exceeded'})
        return responses_api.text('ok')

    responses_api.install(create)
    assert await Analyst(config, runtime.store, None).answer('long', 'current') == 'ok'
    assert len(snapshots[0]) == 51
    assert 1 < len(snapshots[1]) < 51
    assert snapshots[1][0]['role'] == 'user'
    assert snapshots[1][-1]['content'] == 'current'
    assert len(runtime.store.history('long')) == 52


async def test_twenty_tool_rounds_then_final_answer(runtime, responses_api):
    runtime.config.save({'model': 'test', 'max_rounds': 5, 'history_turns': 8}, {'openai_key': 'fake'})
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if kwargs.get('tool_choice') == 'none':
            return responses_api.text('done')
        return responses_api.tool('find_stock_id', '{"keyword":"台積電"}')

    responses_api.install(create)
    market = SimpleNamespace(call=AsyncMock(return_value={'id': '2330'}))
    assert await Analyst(runtime.config, runtime.store, market).answer('s', 'question') == 'done'
    assert market.call.await_count == 20
    assert len(calls) == 21
    assert calls[-1]['tool_choice'] == 'none'
    assert 'max_rounds' not in runtime.config.value.model_dump()
