"""本機設定：一般設定寫入 JSON，金鑰交給作業系統憑證庫。"""
import hashlib
import json
import os
from pathlib import Path

import keyring
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analysis_settings import AnalysisSettings

SECRETS = ("openai_key", "line_token", "line_secret", "telegram_token", "ngrok_token")
ENV = dict(zip(SECRETS, ("OPENAI_API_KEY", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET",
                         "TELEGRAM_BOT_TOKEN", "NGROK_AUTHTOKEN")))


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="", max_length=120)
    line_enabled: bool = False
    telegram_enabled: bool = False
    ngrok_enabled: bool = False
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    timeout_seconds: int = Field(default=150, ge=30, le=300)
    retention_days: int = Field(default=30, ge=1, le=365)
    reply_chars: int = Field(default=5000, ge=500, le=12000)

    @model_validator(mode="before")
    @classmethod
    def remove_legacy_limits(cls, values):
        # 舊設定檔仍可讀取，但不再採用固定對話輪數或舊工具上限。
        if isinstance(values, dict):
            return {k: v for k, v in values.items() if k not in ("history_turns", "max_rounds")}
        return values


class Config:
    def __init__(self, root: Path | None = None, vault=None):
        self.root = root or Path(os.getenv("STOCK_BOT_DATA_DIR", Path.home() / ".stock-bot"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.vault = vault or keyring
        self.service = "stock-bot-" + hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()[:12]
        path = self.root / "settings.json"
        values = json.loads(path.read_text("utf-8")) if path.exists() else {}
        # 舊版允許 181～365 天；載入時調整至新上限，避免舊設定阻止啟動。
        if isinstance(values, dict) and isinstance(values.get('analysis'), dict):
            days = values['analysis'].get('price_days')
            if isinstance(days, int) and 180 < days <= 365:
                values['analysis']['price_days'] = 180
        self.value = Settings.model_validate(values)

    def secret(self, name):
        try:
            saved = self.vault.get_password(self.service, name)
        except Exception:
            saved = None
        return saved or os.getenv(ENV[name], "")

    def public(self):
        return {**self.value.model_dump(), "configured": {k: bool(self.secret(k)) for k in SECRETS}}

    def save(self, values: dict, secrets: dict):
        updated = Settings.model_validate(values)
        if set(secrets) - set(SECRETS):
            raise ValueError("未知的金鑰欄位")
        # 空字串代表不變；明確 null 才刪除憑證庫中的值。
        for name, value in secrets.items():
            try:
                if value is None:
                    if self.vault.get_password(self.service, name):
                        self.vault.delete_password(self.service, name)
                elif value.strip():
                    self.vault.set_password(self.service, name, value.strip())
            except Exception as exc:
                raise ValueError("無法寫入作業系統憑證庫。請使用環境變數設定金鑰，詳見使用指南。") from exc
        temp = self.root / "settings.tmp"
        temp.write_text(updated.model_dump_json(indent=2), "utf-8")
        temp.replace(self.root / "settings.json")
        self.value = updated

