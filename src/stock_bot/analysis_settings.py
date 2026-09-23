"""分析選項白名單；同時供設定驗證與資料工具使用。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PriceField = Literal['close', 'daily_return', 'change', 'period_return', 'volume',
                     'ma5', 'ma20', 'ma60', 'rsi14', 'macd', 'bollinger']
FundamentalField = Literal['revenue', 'eps', 'revenue_growth', 'eps_growth', 'gross_margin',
                           'operating_margin', 'net_margin', 'roe', 'net_income', 'assets',
                           'liabilities', 'equity', 'operating_cashflow', 'free_cashflow',
                           'market_cap', 'trailing_pe', 'forward_pe', 'price_to_book']
DEFAULT_PRICE_FIELDS = ['close', 'daily_return', 'change', 'period_return']
DEFAULT_FUNDAMENTAL_FIELDS = ['revenue', 'eps', 'revenue_growth', 'eps_growth',
                              'gross_margin', 'operating_margin', 'net_margin', 'roe']


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    price_days: int = Field(default=15, ge=3, le=180)
    price_fields: list[PriceField] = Field(default_factory=lambda: DEFAULT_PRICE_FIELDS.copy(), min_length=1, max_length=11)
    fundamental_fields: list[FundamentalField] = Field(
        default_factory=lambda: DEFAULT_FUNDAMENTAL_FIELDS.copy(), min_length=1, max_length=18)
    news_count: int = Field(default=10, ge=5, le=20)
    web_search_enabled: bool = False
