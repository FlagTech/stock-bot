"""延續 6-1：以收盤價計算報酬，取得當下可用行情與新聞內文。"""
import datetime as dt
import difflib
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

from .analysis_settings import AnalysisSettings

TZ = ZoneInfo("Asia/Taipei")


def extract_news_content(html):
    """優先讀取頁面的文章內文，避開頁首推薦新聞與其他導覽段落。"""
    soup = BeautifulSoup(html, 'html.parser')

    def bodies(node):
        if isinstance(node, list):
            for item in node:
                yield from bodies(item)
        elif isinstance(node, dict):
            if isinstance(node.get('articleBody'), str) and node['articleBody'].strip():
                yield node['articleBody']
            yield from bodies(node.get('@graph', []))

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            for body in bodies(json.loads(script.get_text())):
                text = BeautifulSoup(body, 'html.parser').get_text('\n', strip=True)
                if text:
                    return text
        except (ValueError, TypeError):
            continue
    # 結構化內文不存在時，限縮在正文容器；不取全頁 p[4:]，避免混入其他文章。
    for selector in ('[itemprop="articleBody"]', 'article main', 'article'):
        candidates = []
        for container in soup.select(selector):
            for unwanted in container.select('script, style, nav, aside, footer, figure'):
                unwanted.decompose()
            text = '\n\n'.join(p.get_text(' ', strip=True) for p in container.find_all('p') if p.get_text(strip=True))
            if text:
                candidates.append(text)
        if candidates:
            return max(candidates, key=len)
    return ''


def series_dict(series, percent=False, annual=False):
    result = {}
    for date, value in series.items():
        if pd.notna(value) and math.isfinite(float(value)):
            result[date.strftime('%Y' if annual else '%Y-%m-%d')] = (
                f"{float(value) * 100:.2f}%" if percent else round(float(value), 3))
    return result


class Market:
    def __init__(self, root, analysis=None):
        self.root = root
        self.analysis = analysis or AnalysisSettings()
        self.lock = threading.Lock()
        self.cache = {}

    def get_json(self, url, **params):
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def catalog(self):
        path = self.root / 'stocks.json'
        with self.lock:
            old = None
            if path.exists():
                try:
                    old = json.loads(path.read_text('utf-8'))
                    if time.time() - old['updated'] < 86400:
                        return old['rows']
                except (ValueError, KeyError):
                    old = None
            rows = []
            # 日期往前回溯，涵蓋週末與較長連假；不依賴「昨天必定開市」。
            for days in range(15):
                date = (dt.datetime.now(TZ).date() - dt.timedelta(days=days)).strftime('%Y%m%d')
                try:
                    data = self.get_json('https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX',
                                         date=date, type='ALLBUT0999', response='json')
                except (httpx.HTTPError, ValueError):
                    if old:
                        rows.extend(r for r in old['rows'] if r['市場別'] == '上市')
                    break
                for table in data.get('tables', []):
                    fields = table.get('fields', [])
                    if '證券代號' in fields and '證券名稱' in fields:
                        for row in table.get('data', []):
                            rows.append({'股號': row[fields.index('證券代號')],
                                         '股名': row[fields.index('證券名稱')], '市場別': '上市'})
                if rows:
                    break
            try:
                otc = self.get_json('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes')
                rows.extend({'股號': r['SecuritiesCompanyCode'], '股名': r['CompanyName'], '市場別': '上櫃'}
                            for r in otc if r.get('SecuritiesCompanyCode'))
            except (httpx.HTTPError, ValueError, KeyError):
                if old:
                    rows.extend(r for r in old['rows'] if r['市場別'] == '上櫃')
            if not rows:
                if old:
                    return old['rows']
                raise ValueError('目前無法取得股票清單，請稍後再試。')
            path.write_text(json.dumps({'updated': time.time(), 'rows': rows}, ensure_ascii=False), 'utf-8')
            return rows

    def find_stock_id(self, keyword):
        rows = self.catalog()
        matches = [r for r in rows if keyword in r['股名'] or keyword == r['股號']]
        if not matches:
            close = difflib.get_close_matches(keyword, [r['股名'] for r in rows], n=3, cutoff=.5)
            matches = [r for r in rows if r['股名'] in close]
        if not matches:
            return {'訊息': f'找不到名稱包含「{keyword}」的股票'}
        return matches[:20]

    def resolve(self, stock_id):
        if stock_id in ('大盤', '^TWII'):
            return '^TWII', '大盤'
        code = stock_id.upper().removesuffix('.TWO').removesuffix('.TW')
        for row in self.catalog():
            if row['股號'] == code:
                return code + ('.TW' if row['市場別'] == '上市' else '.TWO'), row['股名']
        raise ValueError('找不到股票代號，請先依名稱查詢。')

    def stock_price(self, stock_id='大盤', days=None):
        days = self.analysis.price_days if days is None else days
        fields = set(self.analysis.price_fields)
        ticker, name = self.resolve(stock_id)
        today = dt.datetime.now(TZ).date()
        start = today - dt.timedelta(days=days)
        # 技術指標需暖機資料；輸出仍限於使用者所選期間。
        warmup = 365 if fields & {'ma5', 'ma20', 'ma60', 'rsi14', 'macd', 'bollinger'} else 0
        # 與 6-1 相同，不設定 end；取得來源目前可提供的資料，包含可能的當日資料。
        frame = yf.download(ticker, start=start - dt.timedelta(days=warmup),
                            auto_adjust=False, multi_level_index=False, progress=False, threads=False, timeout=20)
        if frame.empty or 'Close' not in frame:
            raise ValueError('此期間無股價資料，請放大查詢期間或稍後再試。')
        frame = frame.sort_index()
        full_close = frame['Close'].dropna()
        close = full_close.loc[[stamp.date() >= start for stamp in full_close.index]]
        if close.empty:
            raise ValueError('此期間沒有有效收盤價，請稍後再試。')
        # 與筆記本相同，只回傳股號、股名與價格資料，不附來源與說明文字。
        result = {'股票代號': ticker, '股票名稱': name}
        if 'close' in fields:
            result['收盤價'] = series_dict(close)
        if 'change' in fields:
            result['漲跌價差'] = series_dict(close.diff())
        if 'daily_return' in fields:
            result['每日報酬'] = series_dict(close.pct_change(fill_method=None), True)
        if 'period_return' in fields:
            result['期間報酬'] = f'{(close.iloc[-1] / close.iloc[0] - 1) * 100:.2f}%' if len(close) > 1 and close.iloc[0] else None
        if 'volume' in fields:
            result['成交量（股）'] = series_dict(frame['Volume'].reindex(close.index)) if 'Volume' in frame else {}
        indicators = {}
        for period in (5, 20, 60):
            if f'ma{period}' in fields:
                indicators[f'MA{period}'] = full_close.rolling(period).mean()
        if 'rsi14' in fields:
            delta = full_close.diff()
            gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
            # Wilder 平滑，以前 14 個變動的簡單平均初始化。
            def wilder(values):
                seeded = values.copy()
                seeded.iloc[:14] = float('nan')
                if len(seeded) > 14:
                    seeded.iloc[14] = values.iloc[1:15].mean()
                return seeded.ewm(alpha=1/14, adjust=False, ignore_na=True).mean()
            up, down = wilder(gain), wilder(loss)
            rsi = 100 - 100 / (1 + up / down.replace(0, float('nan')))
            rsi = rsi.mask((down == 0) & (up > 0), 100).mask((down == 0) & (up == 0), 50)
            indicators['RSI14（Wilder）'] = rsi
        if 'macd' in fields:
            dif = full_close.ewm(span=12, adjust=False, min_periods=12).mean() - full_close.ewm(span=26, adjust=False, min_periods=26).mean()
            signal = dif.ewm(span=9, adjust=False, min_periods=9).mean()
            indicators.update({'MACD DIF（12,26）': dif, 'MACD 訊號（9）': signal, 'MACD 柱狀（DIF−訊號）': dif - signal})
        if 'bollinger' in fields:
            mid, std = full_close.rolling(20).mean(), full_close.rolling(20).std(ddof=0)
            indicators.update({'布林中軌（20）': mid, '布林上軌（2σ）': mid + 2 * std, '布林下軌（2σ）': mid - 2 * std})
        for label, values in indicators.items():
            result[label] = series_dict(values.reindex(close.index))
        return result

    def stock_fundamental(self, stock_id):
        if stock_id in ('大盤', '^TWII'):
            return None
        ticker, name = self.resolve(stock_id)
        stock = yf.Ticker(ticker)
        fields = set(self.analysis.fundamental_fields)
        result = {'股票代號': ticker, '股票名稱': name}

        def fetch(attr):
            try:
                value = getattr(stock, attr)
                return value if isinstance(value, pd.DataFrame) else pd.DataFrame()
            except Exception:
                return pd.DataFrame()

        income_fields = {'revenue', 'eps', 'revenue_growth', 'eps_growth', 'gross_margin',
                         'operating_margin', 'net_margin', 'net_income', 'roe'}
        balance_fields = {'assets', 'liabilities', 'equity', 'roe'}
        cash_fields = {'operating_cashflow', 'free_cashflow'}
        for label, prefix, annual in [('季報', 'quarterly_', False), ('年報', '', True)]:
            income = fetch(prefix + 'financials') if fields & income_fields else pd.DataFrame()
            balance = fetch(prefix + 'balance_sheet') if fields & (balance_fields - ({'roe'} if not annual else set())) else pd.DataFrame()
            cash = fetch(prefix + 'cashflow') if fields & cash_fields else pd.DataFrame()

            def row(frame, key):
                return frame.loc[key].sort_index() if key in frame.index else pd.Series(dtype=float)

            def growth(values, annual=annual):
                if values.empty:
                    return values
                gaps = pd.Series(values.index, index=values.index).diff().dt.days
                return values.pct_change(fill_method=None).where(gaps.between(330, 400) if annual else gaps.between(70, 110))

            revenue, eps = row(income, 'Total Revenue'), row(income, 'Basic EPS')
            values = {
                'revenue': ('營收', revenue, False), 'eps': ('EPS', eps, False),
                'revenue_growth': ('營收年增率' if annual else '營收季增率', growth(revenue), True),
                'eps_growth': ('EPS 年增率' if annual else 'EPS 季增率', growth(eps), True),
                'net_income': ('淨利', row(income, 'Net Income'), False),
                'assets': ('總資產', row(balance, 'Total Assets'), False),
                'liabilities': ('總負債', row(balance, 'Total Liabilities Net Minority Interest'), False),
                'equity': ('股東權益', row(balance, 'Stockholders Equity'), False),
                'operating_cashflow': ('營業現金流', row(cash, 'Operating Cash Flow'), False),
                'free_cashflow': ('自由現金流', row(cash, 'Free Cash Flow'), False),
            }
            for field, title, key in [('gross_margin', '毛利率', 'Gross Profit'),
                                      ('operating_margin', '營業利益率', 'Operating Income'),
                                      ('net_margin', '淨利率', 'Net Income')]:
                values[field] = (title, row(income, key) / revenue.replace(0, float('nan')), True)
            if annual:
                values['roe'] = ('ROE（期末權益）', row(income, 'Net Income') / row(balance, 'Stockholders Equity').replace(0, float('nan')), True)
            item = {title: series_dict(series, percent, annual)
                    for field, (title, series, percent) in values.items() if field in fields}
            if item:
                result[label] = item
        info_fields = {'market_cap': ('市值', 'marketCap'), 'trailing_pe': ('本益比（TTM）', 'trailingPE'),
                       'forward_pe': ('預估本益比', 'forwardPE'), 'price_to_book': ('股價淨值比', 'priceToBook')}
        if fields & info_fields.keys():
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            snapshot = {'報價幣別': info.get('currency'), '財報幣別': info.get('financialCurrency')}
            for field, (title, key) in info_fields.items():
                if field in fields:
                    value = info.get(key)
                    snapshot[title] = value if isinstance(value, (int, float)) and math.isfinite(value) else None
            result['估值快照'] = snapshot
        return result

    def stock_news(self, stock_id, count=None):
        count = self.analysis.news_count if count is None else count
        _, name = self.resolve(stock_id)
        payload = self.get_json('https://ess.api.cnyes.com/ess/api/v1/news/keyword',
                                q='台股 -盤中速報' if name == '大盤' else name, limit=count, page=1)
        items = payload.get('data', {}).get('items', [])
        def fetch_article(item):
            url = f"https://news.cnyes.com/news/id/{item['newsId']}"
            article = {'日期': dt.datetime.fromtimestamp(item['publishAt'], TZ).strftime('%Y-%m-%d'),
                       '標題': item.get('title', ''), '內容': ''}
            try:
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    article['內容'] = extract_news_content(response.text)
            except (httpx.HTTPError, ValueError):
                pass  # 內文下載失敗時保留標題，內容留空
            return article

        # 有界並行下載，單篇失敗不丟棄其他新聞；map 保留來源順序。
        with ThreadPoolExecutor(max_workers=4) as pool:
            articles = list(pool.map(fetch_article, items[:count]))
        return {'股票代號': stock_id, '股票名稱': name, '新聞': articles}

    def stock_trend_report(self, stock_id):
        result = {}
        for name in ('stock_price', 'stock_fundamental', 'stock_news'):
            try:
                result[name] = getattr(self, name)(stock_id)
            except Exception:
                result[name] = {'錯誤': '此來源暫時無法取得資料，請明確標示缺項。'}
        return result

    def call(self, name, args):
        key = json.dumps([name, args], sort_keys=True)
        cached = self.cache.get(key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        value = getattr(self, name)(**args)
        if len(self.cache) > 100:
            self.cache.clear()
        self.cache[key] = (time.time(), value)
        return value
