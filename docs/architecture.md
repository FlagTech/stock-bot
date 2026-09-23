# 架構與第六章範例對照

## 延續第五章

保留 React + FastAPI、uv.lock、start.bat、自動開啟瀏覽器及網頁設定方式。兩個專案獨立安裝、獨立資料目錄、獨立連接埠；不需安裝或啟動第五章專案。

## 模組

| 檔案 | 職責 | Notebook 對應 |
|---|---|---|
| `config.py` | Pydantic 設定、系統憑證庫 | API Key、MODEL |
| `market.py` | 股票清單、報價、財報、新聞 | stock_name、resolve_stock_id、find_stock_id、stock_price、stock_fundamental、stock_news、stock_trend_report |
| `ai.py` | 工具 schema、參數驗證、模型迴圈、錯誤訊息 | TOOLS、AVAILABLE_TOOLS、get_tool_reply、stock_gpt |
| `tool_worker.py` | 可被終止的股票工具程序 | 將同步資料查詢與主服務隔離 |
| `storage.py` | SQLite 工作佇列、歷史與 offset | hist，改為每段對話獨立儲存 |
| `platforms.py` | LINE API、Telegram 長輪詢、分段傳送 | 新增聊天平台入口 |
| `tunnel.py` | 本專案 ngrok 程序生命週期 | 新增公開 Webhook 通道 |
| `runtime.py` | 兩個背景工作、啟停與狀態 | 取代 Notebook 手動執行 |
| `api.py` | 控制台與 Webhook 分別建立 FastAPI app | 新增本機管理與訊息接收 |
| `__init__.py` | CLI、單程序鎖、雙服務啟動 | 新增成品啟動方式 |

## 訊息生命週期

LINE：驗證原始請求簽章 → 持久寫入工作 → HTTP 200 → 背景回覆接收通知 → AI 分析 → Push API。
Telegram：getUpdates → 寫入工作 → 保存 offset → 下一次 getUpdates 確認 → AI 分析 → sendMessage。
本機：送出問題 → 寫入工作 → 輪詢工作狀態 → 顯示結果。

工作狀態：queued → running → sending（外部平台）→ done。
失敗進入 failed；程序重啟時 running 轉 interrupted，sending 轉 uncertain。後兩者要求查看平台紀錄再決定是否重新提問。

同段對話不允許兩個 running/sending 工作；另外一位使用者可同時分析。工具 round 上限之外，還有每輪五個工具與整體時間限制。子程序逾時或取消會被終止。

資料提供者為外部、不保證可用的來源。工具失敗轉成缺項，模型不得用內建知識補造近期數字。新聞逐篇下載原文頁，優先解析 articleBody、其次擷取正文段落；最多四篇並行，每篇連線逾時 10 秒。失敗保留標題與連結，明確標示未取得內文。

行情沿用 6-1：不設定下載 end，保留來源可提供的當日資料；Close 用於報價、每日報酬與期間報酬。當日資料可能尚未定案；工具輸出與系統提示詞皆與第六章筆記本相同，不另附來源或說明欄位。先前版本的「調整後每日報酬／調整後期間報酬」欄位已改為「每日報酬／期間報酬」；既有歷史報告不改寫，新查詢採用一致口徑。

## 管理介面隔離

8767 只綁 127.0.0.1：設定、試聊、工作紀錄。檢查 Host、Origin 與每次啟動產生的 CSRF token，不允許任意網站呼叫本機修改 API。

8768 只綁 127.0.0.1，由 ngrok 公開：僅 `/health` 與 `/line/webhook`。沒有設定 API、靜態頁、工作紀錄或 OpenAPI 文件。LINE 驗證在 JSON 解碼前進行，使用 constant-time compare。

金鑰不傳入股票查詢子程序的環境；對外 SDK 原始錯誤不傳回介面。憑證庫是金鑰保存機制，不是防範同帳號惡意程式的安全邊界。

## 擴充方向

群組對話需設計聊天室與發問者的脈絡隔離及機器人觸發規則；不能直接放開目前私人聊天檢查。
新增資料來源可由 Market 工具提供統一格式。真實下單不在本專案範圍。
若改為雲端或多人服務，需另加管理身分驗證、用量限制、佇列容量規劃及對話資料治理。
