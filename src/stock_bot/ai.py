import datetime as dt
import json
from copy import deepcopy

from openai import AsyncOpenAI, AuthenticationError, BadRequestError, NotFoundError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from .market import TZ
from .web_search import SEARCH_UNSUPPORTED, WEB_SEARCH_TOOL, citations, search_web


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StockArgs(Args):
    stock_id: str = Field(pattern=r'^(大盤|\^TWII|[0-9A-Z]{4,6}(\.TW|\.TWO)?)$')


class PriceArgs(StockArgs):
    days: int = Field(default=15, ge=3, le=180)


class NewsArgs(StockArgs):
    count: int = Field(default=10, ge=1, le=20)


class FindArgs(Args):
    keyword: str = Field(min_length=1, max_length=40)


TOOLS = {
    'find_stock_id': (FindArgs, '依公司名稱尋找台股代號；多個或模糊結果先向使用者確認。'),
    'stock_price': (PriceArgs, '查收盤價與以收盤價計算的報酬；days 是日曆天，包含來源可提供的當日資料，當日數值可能未定案。'),
    'stock_fundamental': (StockArgs, '取得季報與年報，缺項不代表零。'),
    'stock_news': (NewsArgs, '取得近期新聞全文並標示擷取狀態；未指定篇數時省略 count，使用已儲存的新聞篇數設定。'),
    'stock_trend_report': (StockArgs, '整合股價、財報與新聞，用於趨勢分析。'),
}
SCHEMAS = [{'type': 'function', 'name': name, 'description': description,
            'parameters': model.model_json_schema()} for name, (model, description) in TOOLS.items()]
MAX_TOOL_ROUNDS = 20
TOOL_LABELS = {'find_stock_id': '股票代號查詢', 'stock_price': '股價查詢', 'stock_fundamental': '財報查詢',
               'stock_news': '新聞查詢', 'stock_trend_report': '趨勢報告'}
# store=False 時需帶回加密推理內容，推理模型才能在多輪工具呼叫間延續思路。
RESPONSE_OPTIONS = {'store': False, 'include': ['reasoning.encrypted_content']}
SEARCH_ON = ('網路搜尋開啟：可視問題需要使用 web_search 補充最新消息或查證，僅搜尋與當前股票問題相關的公開資料，'
             '引用搜尋資料須附來源連結。')
SEARCH_OFF = '網路搜尋未開啟，不可聲稱已搜尋網路。'

# 與第六章筆記本 stk_ch06.ipynb 的 sys_msg 相同。
SYSTEM = '''你是一位專業的證券分析師，你沒有股價、基本面、
新聞的即時資料，任何具體數字或近期消息都必須先呼叫對應的工具
取得，不能憑自己的知識回答或臆測。取得資料後，統整成詳細、嚴謹
及專業的分析，並提及重要的數字，使用繁體中文回覆'''


class Analyst:
    def __init__(self, config, store, market):
        self.config, self.store, self.market = config, store, market

    async def answer(self, session, text, progress=None):
        command = text.strip().lower()
        if command in ('/start', '/help', '說明'):
            return '歡迎使用 Stock Bot！可問「台積電近 30 天股價」、「比較鴻海與台積電」、「分析大盤趨勢」。/reset 清除這段對話。'
        if command in ('/reset', '清除對話'):
            self.store.reset(session)
            return '已清除這段對話，請開始新的問題。'
        settings = self.config.value
        analysis = settings.analysis
        key = self.config.secret('openai_key')
        if not key or not settings.model:
            raise ValueError('請先在設定頁填入 OpenAI 金鑰與模型，並測試連線。')
        instructions = SYSTEM + f'\n今天是 {dt.datetime.now(TZ).date()}。回答不超過 {settings.reply_chars} 字。'
        instructions += (
            f'\n分析設定：{analysis.model_dump_json()}。價格天期為日曆天；未明確指定天期或新聞篇數，'
            '呼叫工具時省略 days / count，採用設定值。只分析勾選欄位；未勾選資料不自行推估。\n')
        search = analysis.web_search_enabled
        sources = {}
        search_errors = []
        schemas = deepcopy(SCHEMAS)
        for schema in schemas:
            properties = schema['parameters']['properties']
            if 'days' in properties:
                properties['days']['default'] = analysis.price_days
            if 'count' in properties:
                properties['count']['default'] = analysis.news_count
        history = self.store.history(session)
        items = history + [{'role': 'user', 'content': text}]
        history_count = len(history)
        async with AsyncOpenAI(api_key=key, timeout=90, max_retries=1) as client:
            for iteration in range(MAX_TOOL_ROUNDS + 1):
                # 最後一輪保留工具定義但禁止呼叫，讓模型依已取得資料作答。
                final_round = {'tool_choice': 'none'} if iteration == MAX_TOOL_ROUNDS else {}
                while True:
                    extra = {'tools': schemas + [WEB_SEARCH_TOOL], 'max_tool_calls': 3} if search else {'tools': schemas}
                    try:
                        response = await client.responses.create(
                            model=settings.model, instructions=instructions + (SEARCH_ON if search else SEARCH_OFF),
                            input=items, **RESPONSE_OPTIONS, **extra, **final_round)
                        break
                    except BadRequestError as exc:
                        if exc.code == 'context_length_exceeded':
                            if not history_count:
                                raise ValueError('本次問題與工具資料已超過模型上下文容量，請縮小分析範圍。') from exc
                            # 以完整問答為單位縮減最舊的一半；保留本輪工具鏈。
                            drop = min(history_count, max(2, ((history_count // 2 + 1) // 2) * 2))
                            items = items[drop:]
                            history_count -= drop
                        elif search:
                            # 模型或帳號不支援內建搜尋時，關閉搜尋重試並在回答附註，不暗中更換模型。
                            search = False
                            search_errors.append('網路搜尋未完成：' + SEARCH_UNSUPPORTED)
                        else:
                            raise
                sources.update(citations(response.output))
                calls = [item for item in response.output if item.type == 'function_call']
                if not calls:
                    answer = response.output_text
                    if not answer:
                        raise ValueError('模型沒有回傳文字，請調整問題或模型。')
                    if len(answer) > settings.reply_chars:
                        answer = answer[:settings.reply_chars] + '\n（已達回覆長度上限，請縮小問題範圍。）'
                    if sources:
                        answer += '\n\n網路搜尋來源：\n' + '\n'.join(
                            f'[{i}](<{url}>)' for i, url in enumerate(sources, 1))
                    if search_errors:
                        answer += '\n\n' + '\n'.join(dict.fromkeys(search_errors))
                    self.store.remember(session, text, answer)
                    return answer
                items += [item.model_dump(exclude_none=True) for item in response.output]
                if progress:
                    names = dict.fromkeys(TOOL_LABELS.get(call.name, call.name) for call in calls[:5])
                    progress(f'正在呼叫 {"、".join(names)} 工具')
                for index, call in enumerate(calls):
                    try:
                        if index >= 5:
                            raise ValueError('每輪最多執行五個工具。')
                        model, _ = TOOLS[call.name]
                        args = model.model_validate_json(call.arguments)
                        result = await self.market.call(call.name,
                            {**args.model_dump(exclude_unset=True), 'analysis': analysis.model_dump()})
                    except Exception:
                        result = {'錯誤': '工具參數不合規或資料來源暫時不可用。請明確說明資料不足，不編造數字。'}
                    items.append({'type': 'function_call_output', 'call_id': call.call_id,
                                  'output': json.dumps(result, ensure_ascii=False, allow_nan=False)})
                if progress:
                    progress('')  # 工具執行完畢，回到模型分析階段
        raise ValueError('分析已達工具呼叫上限，請縮小問題範圍。')

    async def test(self):
        if not self.config.secret('openai_key') or not self.config.value.model:
            raise ValueError('請先儲存 OpenAI 金鑰與模型名稱。')
        async with AsyncOpenAI(api_key=self.config.secret('openai_key'), timeout=60, max_retries=0) as client:
            r = await client.responses.create(model=self.config.value.model, **RESPONSE_OPTIONS,
                input='請呼叫 find_stock_id，keyword 使用台積電。',
                tools=SCHEMAS[:1], tool_choice={'type': 'function', 'name': 'find_stock_id'})
            calls = [item for item in r.output if item.type == 'function_call']
            if not calls or calls[0].name != 'find_stock_id':
                raise ValueError('模型未回傳預期工具呼叫，請選擇支援工具的模型。')
            FindArgs.model_validate_json(calls[0].arguments)
            if self.config.value.analysis.web_search_enabled:
                await search_web(client, self.config.value.model, '臺灣證券交易所官方網站')
                return '模型、工具呼叫與 OpenAI 內建網路搜尋測試成功。此測試會產生 API 與搜尋用量。'
        return '模型連線與工具呼叫測試成功。此測試會產生少量 API 用量。'


def friendly_error(exc):
    # 不能將包含網址、權杖或 SDK 原始回應的例外回傳給使用者。
    if isinstance(exc, AuthenticationError):
        return 'OpenAI 金鑰無效或已撤銷，請更新設定。'
    if isinstance(exc, RateLimitError):
        return 'OpenAI 額度不足或請求過於頻繁，請檢查帳號用量。'
    if isinstance(exc, NotFoundError):
        return '找不到此模型，或帳號無權使用，請確認模型名稱。'
    if isinstance(exc, BadRequestError):
        return 'OpenAI 拒絕此請求，請確認模型名稱正確且支援 Responses API 與工具呼叫。'
    if isinstance(exc, TimeoutError):
        return '分析超過時間上限，請縮小問題範圍後重試。'
    if isinstance(exc, ValueError) and type(exc) is ValueError:
        return str(exc)
    return '服務暫時無法完成請求，請檢查設定及網路後重試。'
