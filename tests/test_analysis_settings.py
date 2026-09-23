import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import pytest
from openai import BadRequestError
from pydantic import ValidationError

from stock_bot.ai import Analyst
from stock_bot.analysis_settings import AnalysisSettings, DEFAULT_FUNDAMENTAL_FIELDS
from stock_bot.config import Config, Settings
from stock_bot.market import Market, TZ
from stock_bot.web_search import search_web


def test_defaults_migration_and_persistence(config):
    assert AnalysisSettings().price_days == 15
    assert AnalysisSettings(price_days=3).price_days == 3
    assert AnalysisSettings(price_days=180).price_days == 180
    assert Settings.model_validate({'model': 'test', 'history_turns': 8}).analysis.fundamental_fields == DEFAULT_FUNDAMENTAL_FIELDS
    options = AnalysisSettings(price_days=90, price_fields=['volume', 'ma20'], news_count=20, web_search_enabled=True)
    config.save({'analysis': options.model_dump()}, {})
    loaded = Config(config.root, config.vault)
    assert loaded.value.analysis == options


@pytest.mark.parametrize('options', [
    {'news_count': 4}, {'news_count': 21}, {'price_days': 0}, {'price_days': 181},
    {'price_fields': []}, {'fundamental_fields': []}, {'price_fields': ['invented']},
])
def test_invalid_analysis_settings_rejected(options):
    with pytest.raises(ValidationError):
        AnalysisSettings(**options)


def test_legacy_long_period_loads_at_new_limit(config):
    (config.root / 'settings.json').write_text('{"analysis":{"price_days":365}}', encoding='utf-8')
    assert Config(config.root, config.vault).value.analysis.price_days == 180


def test_indicators_use_warmup_and_filter_output(tmp_path, monkeypatch):
    today = dt.datetime.now(TZ).date()
    index = pd.date_range(end=today, periods=100)
    frame = pd.DataFrame({'Close': range(1, 101), 'Volume': 300}, index=index)
    market = Market(tmp_path, AnalysisSettings(price_days=5, price_fields=['volume', 'ma20', 'rsi14', 'macd', 'bollinger']))
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))

    def download(*args, **kwargs):
        assert kwargs['start'] == today - dt.timedelta(days=370)
        assert kwargs['auto_adjust'] is False
        return frame

    monkeypatch.setattr('stock_bot.market.yf.download', download)
    result = market.stock_price('2330')
    assert '收盤價' not in result and '每日報酬' not in result
    assert len(result['MA20']) == 6
    assert result['MA20'][str(today)] == 90.5
    assert result['RSI14（Wilder）'][str(today)] == 100
    assert result['布林上軌（2σ）'][str(today)] == round(90.5 + 2 * pd.Series(range(81, 101)).std(ddof=0), 3)
    assert result['MACD DIF（12,26）'][str(today)] == pytest.approx(7, abs=.01)
    assert result['成交量（股）'][str(today)] == 300


def test_fundamental_selection_and_partial_sources(tmp_path, monkeypatch):
    dates = pd.to_datetime(['2025-12-31'])
    class Stock:
        balance_sheet = pd.DataFrame([[200], [80]], index=['Total Assets', 'Stockholders Equity'], columns=dates)
        quarterly_balance_sheet = balance_sheet
        cashflow = pd.DataFrame([[30]], index=['Operating Cash Flow'], columns=dates)
        quarterly_cashflow = cashflow
        info = {'trailingPE': 20, 'marketCap': float('nan'), 'currency': 'TWD'}
        @property
        def financials(self):
            raise AssertionError('Unselected source must not be fetched')
    monkeypatch.setattr('stock_bot.market.yf.Ticker', lambda _: Stock())
    market = Market(tmp_path, AnalysisSettings(fundamental_fields=['assets', 'operating_cashflow', 'free_cashflow', 'market_cap', 'trailing_pe']))
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))
    result = market.stock_fundamental('2330')
    assert result['年報']['總資產'] == {'2025': 200}
    assert 'EPS' not in result['年報']
    assert result['年報']['營業現金流'] == {'2025': 30}
    assert result['年報']['自由現金流'] == {}
    assert result['估值快照']['市值'] is None
    assert result['估值快照']['本益比（TTM）'] == 20


def test_news_uses_saved_count_and_explicit_override(tmp_path, monkeypatch):
    market = Market(tmp_path, AnalysisSettings(news_count=20))
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))
    counts = []
    def get_json(*args, **kwargs):
        counts.append(kwargs['limit'])
        return {'data': {'items': []}}
    monkeypatch.setattr(market, 'get_json', get_json)
    assert market.stock_news('2330')['新聞'] == []
    assert market.stock_news('2330', 5)['新聞'] == []
    assert counts == [20, 5]


def search_response():
    citation = SimpleNamespace(type='url_citation', url='https://example.com/news', title='News')
    content = SimpleNamespace(type='output_text', annotations=[citation])
    return SimpleNamespace(output_text='新聞摘要', output=[SimpleNamespace(type='message', content=[content])])


async def test_builtin_search_request_and_citations():
    create = AsyncMock(return_value=search_response())
    result = await search_web(SimpleNamespace(responses=SimpleNamespace(create=create)), 'test', '台積電新聞')
    assert create.await_args.kwargs['tools'] == [{'type': 'web_search'}]
    assert create.await_args.kwargs['store'] is False
    assert create.await_args.kwargs['tool_choice'] == 'required'
    assert result['來源'][0]['網址'] == 'https://example.com/news'


async def test_unsupported_search_is_actionable():
    error = BadRequestError('secret provider detail', response=httpx.Response(400, request=httpx.Request('POST', 'https://example.com')),
                            body={'code': 'unsupported_tool'})
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=error)))
    with pytest.raises(ValueError, match='支援 OpenAI') as exc:
        await search_web(client, 'test', 'news')
    assert 'secret' not in str(exc.value)


async def test_search_without_citations_is_not_presented_as_verified():
    response = SimpleNamespace(output_text='沒有來源的摘要', output=[])
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=response)))
    with pytest.raises(ValueError, match='附來源'):
        await search_web(client, 'test', 'news')


async def test_worker_accepts_analysis_options_without_network(tmp_path):
    from stock_bot.tool_worker import IsolatedMarket
    options = AnalysisSettings(news_count=20, price_fields=['ma20'])
    result = await IsolatedMarket(tmp_path).call('stock_fundamental',
        {'stock_id': '^TWII', 'analysis': options.model_dump()})
    assert result is None  # 與筆記本相同，大盤沒有基本面資料


@pytest.mark.parametrize('enabled', [False, True])
async def test_analysis_flow_applies_options_and_search_gate(runtime, responses_api, enabled):
    runtime.config.save({'model': 'test', 'analysis': {'price_days': 90, 'news_count': 20,
                         'price_fields': ['volume'], 'web_search_enabled': enabled}}, {'openai_key': 'fake'})
    if enabled:
        # 內建搜尋在同一次呼叫內完成，來源從最終訊息的引用取得。
        replies = [responses_api.text('完成', search_response().output)]
    else:
        replies = [responses_api.tool('stock_price', '{"stock_id":"2330"}'), responses_api.text('完成')]
    create = AsyncMock(side_effect=replies)
    responses_api.install(create)
    market = SimpleNamespace(call=AsyncMock(return_value={'成交量': 100}))
    answer = await Analyst(runtime.config, runtime.store, market).answer('s', '分析台積電')
    request = create.await_args_list[0].kwargs
    assert ({'type': 'web_search'} in request['tools']) == enabled
    assert ('max_tool_calls' in request) == enabled
    price_schema = next(t for t in request['tools'] if t.get('name') == 'stock_price')
    assert price_schema['parameters']['properties']['days']['default'] == 90
    if enabled:
        assert 'https://example.com/news' in answer
        market.call.assert_not_awaited()
    else:
        assert '不可聲稱已搜尋網路' in request['instructions']
        args = market.call.await_args.args[1]
        assert 'days' not in args
        assert args['analysis']['price_days'] == 90
        assert args['analysis']['price_fields'] == ['volume']


async def test_unsupported_builtin_search_falls_back_with_notice(runtime, responses_api):
    runtime.config.save({'model': 'test', 'analysis': {'web_search_enabled': True}}, {'openai_key': 'fake'})
    error = BadRequestError('secret provider detail', response=httpx.Response(400, request=httpx.Request('POST', 'https://example.com')),
                            body={'code': 'unsupported_tool'})
    create = AsyncMock(side_effect=[error, responses_api.text('完成')])
    responses_api.install(create)
    answer = await Analyst(runtime.config, runtime.store, None).answer('s', '分析台積電')
    retry = create.await_args_list[1].kwargs
    assert {'type': 'web_search'} not in retry['tools'] and 'max_tool_calls' not in retry
    assert '不可聲稱已搜尋網路' in retry['instructions']
    assert '網路搜尋未完成' in answer and 'secret' not in answer
