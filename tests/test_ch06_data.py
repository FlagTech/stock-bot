import datetime as dt
import json

import httpx
import pandas as pd
import pytest

from stock_bot.market import Market, TZ, extract_news_content


@pytest.mark.parametrize('offset', [0, 1])
def test_price_uses_available_data_and_labels_today(tmp_path, monkeypatch, offset):
    market = Market(tmp_path)
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))
    date = dt.datetime.now(TZ).date() - dt.timedelta(days=offset)
    frame = pd.DataFrame({'Close': [100., 105.]}, index=pd.to_datetime([date-dt.timedelta(days=1), date]))
    def download(*args, **kwargs):
        assert 'end' not in kwargs  # 和筆記本相同，不截掉當天；不依賴 Adj Close。
        assert kwargs['auto_adjust'] is False
        return frame
    monkeypatch.setattr('stock_bot.market.yf.download', download)
    result = market.stock_price('2330')
    assert result['期間報酬'] == '5.00%'
    assert result['每日報酬'][str(date)] == '5.00%'
    # 與筆記本相同，不附來源、網址與說明文字。
    assert not {'來源', '網址', '說明', '資料狀態'} & result.keys()


def test_no_valid_close_is_a_clear_error(tmp_path, monkeypatch):
    market = Market(tmp_path)
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))
    monkeypatch.setattr('stock_bot.market.yf.download', lambda *a, **k: pd.DataFrame({'Close':[float('nan')]}))
    with pytest.raises(ValueError, match='有效收盤價'):
        market.stock_price('2330')


def test_structured_news_body_not_headlines_or_navigation():
    data = {'@graph':[{'@type':'NewsArticle','articleBody':'<p>第一段正文。</p><p>第二段正文。</p>'}]}
    html = '<p>其他新聞標題</p><script type="application/ld+json">' + json.dumps(data) + '</script><footer>頁尾</footer>'
    assert extract_news_content(html) == '第一段正文。\n第二段正文。'


def test_article_paragraph_fallback_excludes_unrelated_text():
    html = '''<p>導覽新聞</p><script type="application/ld+json">invalid</script>
    <article><h1>標題</h1><p>摘要</p><main><p>正文一</p><p>正文二</p>
    <aside><p>推薦新聞</p></aside><footer><p>版權</p></footer></main></article>'''
    assert extract_news_content(html) == '正文一\n\n正文二'


def test_unrecognized_page_does_not_masquerade_as_news():
    assert extract_news_content('<nav><p>網站選單</p></nav><p>Access denied</p>') == ''


def test_news_downloads_content_and_keeps_partial_failures(tmp_path, monkeypatch):
    market = Market(tmp_path)
    monkeypatch.setattr(market, 'resolve', lambda _: ('2330.TW', '台積電'))
    monkeypatch.setattr(market, 'get_json', lambda *a, **k: {'data':{'items':[
        {'newsId':i,'title':f'新聞{i}','publishAt':1700000000} for i in range(3)]}})
    def handler(request):
        if request.url.path.endswith('/0'):
            return httpx.Response(200, text='<article><p>實際的新聞內文。</p></article>')
        if request.url.path.endswith('/1'):
            return httpx.Response(503)
        return httpx.Response(200, text='<p>其他導覽資訊</p>')
    real_client = httpx.Client
    monkeypatch.setattr('stock_bot.market.httpx.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    news = market.stock_news('2330', 3)['新聞']
    assert [item['標題'] for item in news] == ['新聞0', '新聞1', '新聞2']
    assert news[0]['內容'] == '實際的新聞內文。'
    assert news[1]['內容'] == '' and news[2]['內容'] == ''
    assert all(item.keys() == {'日期', '標題', '內容'} for item in news)
