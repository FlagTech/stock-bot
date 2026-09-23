# Stock Bot

第六章雙平台 AI 股票分析機器人。在本機網頁設定 OpenAI、LINE、Telegram，讓聊天軟體共用股票分析核心。

採用 React + TypeScript + FastAPI，延續第五章的 Python / uv 安裝與啟動方式。附建置完成的前端，一般使用不需 Node.js。

## 快速開始

在本專案的 GitHub 頁面點選 **Code → Download ZIP**，下載後完整解壓縮，再依下列方式啟動。無需另外下載發行包。

已完成第五章 Python 與 uv 安裝者可直接使用。本專案以 Python 3.12 鎖定環境，uv 可自動準備對應版本。

Windows：完整解壓縮後，雙擊 **start.bat**。第一次需要網路下載套件。

macOS / Linux：在專案根目錄執行：

```sh
uv sync --locked
uv run --locked stock-bot
```

控制台會自動開啟 **http://127.0.0.1:8767**。瀏覽器未開啟時可手動輸入。
保持終端機視窗開啟，按 Ctrl+C 停止。關閉瀏覽器不會停止程式；電腦關機或休眠後不能提供服務。

第五章使用 8765；本專案控制台 8767、LINE 接收服務 8768，可同時使用。

```sh
uv run --locked stock-bot --port 8777 --webhook-port 8778 --no-browser
```

同一資料目錄只允許一個程序，避免 Telegram 重複輪詢、同一工作重複處理。

## 建議設定順序

1. **設定**：填入 OpenAI API Key 與模型 ID，儲存後測試。模型必須支援工具呼叫。
2. **本機試聊**：先送 `/help`（不需要金鑰），再問「台積電近 30 天股價」。AI 查詢與連線測試會產生 API 用量。
3. **平台串接**：只設定想使用的平台；可單獨啟用 LINE、Telegram，或同時啟用。
4. **工作紀錄**：查看排隊、分析、傳送、成功或失敗狀態。

OpenAI 金鑰與模型請在本專案的設定頁手動填入，並測試工具呼叫能力。

### Telegram

1. 在 [BotFather](https://t.me/BotFather) 輸入 `/newbot`，依指示建立機器人。
2. 將 Bot token 填入平台設定，勾選「啟用 Telegram」，按 Telegram 區塊的「儲存並套用 Telegram」。
3. 測試連線後，在 Telegram 搜尋機器人的使用者名稱（或點 BotFather 訊息中的連結），傳送 `/start`。
4. 本機使用長輪詢，不需要 Webhook 或 ngrok。

同一 Bot 不可同時由另一個程式輪詢。若已有 Webhook，介面會提示衝突；先停止舊服務，再明確按「解除舊 Webhook」。系統不自動覆蓋原有服務。

### LINE 與 ngrok

1. 依 [LINE 官方步驟](https://developers.line.biz/zh-hant/docs/messaging-api/getting-started/) 建立官方帳號並啟用 Messaging API。
2. 在 LINE Developers 的對應 Channel 找到 **Channel secret**，並取得 **Channel access token**。
3. 註冊 [ngrok](https://dashboard.ngrok.com/)，取得 [authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)。
4. 在平台設定填入上述三項金鑰，勾選「啟用 LINE」和「隨 LINE 啟動 ngrok 通道」，按 LINE 區塊的「儲存並套用 LINE」。

兩個平台各自儲存、各自重啟：儲存 Telegram 不會中斷 LINE 與 ngrok 通道，反之亦然；在「設定」頁修改模型或分析項目也不會中斷平台連線。
5. 首次啟動會透過 pyngrok 下載官方 ngrok 執行檔；成功後，複製完整的 `https://…/line/webhook` 網址。
6. 貼到 LINE Developers → Messaging API → Webhook settings → Webhook URL，按 **Verify**，開啟 **Use webhook**。
7. 在官方帳號回應設定中，關閉不需要的預設自動回應，避免每則問題出現額外訊息。
8. 加入官方帳號為好友，傳送問題，確認控制台的「最近收到訊息」更新。

「權杖有效」只表示 API 認證成功；Channel secret 必須靠已簽章的真實 Webhook 驗證。
LINE 一般會先收到「處理中」通知，再收到推播結果。最終結果和長文分段涉及 LINE 推播額度，與 ngrok、OpenAI 各自計量。
ngrok 的開發網域及額度依帳號方案，請查看 [官方限制](https://ngrok.com/docs/pricing-limits/free-plan-limits)。通道只公開 8768 的 Webhook 接收服務，不能取得控制台、設定或對話紀錄。

若已有自己的 HTTPS 通道，可不勾選 ngrok，自行指向 `http://127.0.0.1:8768` 並使用 `/line/webhook` 路徑。**不要將通道指向控制台連接埠。**

## 股票分析

- 依名稱尋找上市、上櫃股票與 ETF，模糊名稱請先確認代號。
- 收盤價、價格變化及以收盤價計算的報酬，與 6-1 相同。包含來源當下可提供的當日資料，但不保證即時或已定案。
- 季報、年報、營收成長、EPS、利潤率與期末股東權益 ROE；ETF 可能沒有公司財報。
- 預設取得 10 篇鉅亨新聞並逐篇擷取內文，附標題、日期、來源連結與擷取狀態；來源不足 10 篇時依實際數量回傳。單篇下載或正文辨識失敗時，保留標題與連結並明確標示，其他篇繼續分析。
- 整合趨勢報告，來源失效會標示缺項。
- 依平台及私人使用者隔離對話，`/reset` 清除該段對話脈絡。

查詢期間是日曆天，不是交易日。報價、漲跌與報酬皆使用 `Close`（`auto_adjust=False`），不以 `Adj Close` 計算，非股息再投資的還原報酬。不設定下載結束日期，與 6-1 相同取得來源當下可用資料；若包含今日，當日數值可能尚未收盤或未更新完成。工具輸出與第六章筆記本相同，只含股號、股名與數據，不附來源、網址與說明文字。財報日期是會計期間，非公布日；成長率名稱區分季增與年增，缺期不跨期計算。這些功能用於資料研究，不執行交易。

新聞優先讀取頁面的結構化 `articleBody`，缺少時擷取正文容器中的段落，避開頁首推薦新聞及導覽。這延續 6-1「進入新聞頁擷取內文」的資料依據，並改善全頁段落切片容易混入其他內容的問題。網站改版、存取限制或來源內容不完整，仍可能導致內文缺漏，此時該篇「內容」為空。每篇新聞與筆記本相同，只有日期、標題、內容。

## 本機資料與金鑰

預設資料目錄：`~/.stock-bot/`，可用環境變數 `STOCK_BOT_DATA_DIR` 指定其他位置。

| 項目 | 儲存方式 |
|---|---|
| 模型、功能開關、分析限制 | `settings.json`，不含金鑰 |
| 工作、對話、接收進度 | `stock-bot.sqlite3` |
| 股票名稱對照快取 | `stocks.json` |
| 通道工具 | `ngrok/`、`ngrok.yml` |
| 金鑰 | 作業系統憑證庫，由 keyring 管理 |

Windows 使用 Windows Credential Manager；macOS 使用 Keychain；Linux 需要可用的 keyring backend。
若無憑證庫，可在啟動環境中設定：

```text
OPENAI_API_KEY
LINE_CHANNEL_ACCESS_TOKEN
LINE_CHANNEL_SECRET
TELEGRAM_BOT_TOKEN
NGROK_AUTHTOKEN
```

程式先讀取憑證庫，再使用環境變數。設定頁空白金鑰欄代表保留；金鑰不回傳給網頁。這一版不自動讀取 `.env`，避免誤以為分享專案資料夾就能安全分享設定。
資料庫包含對話明文；請勿分享整個資料目錄。需要協助時，使用「匯出診斷資訊」，其內容不含金鑰、對話或聊天識別碼。
紀錄保留 30 天；啟動與每小時清理過期紀錄，也可在沒有工作執行時手動清除。

## 可靠性與限制

- 工作先寫入 SQLite；LINE 依事件 ID 去重，Telegram 在保存工作後才推進接收 offset。
- 同一段對話依序處理，不同對話最多兩個工作並行。
- 外部股票資料查詢使用可終止的子程序。達到整體時間上限後會結束查詢；已送到 OpenAI 的請求仍可能計费。
- 重新啟動：排隊工作繼續；分析中工作標為已中斷；傳送中工作標為待確認，不盲目重送。
- LINE 推播重試使用同一 retry key；Telegram 傳送結果不明時不自動重送。不同平台無法提供跨網路的「恰好一次送達」保證。
- 第一版只接收**私人文字訊息**，忽略群組、圖片與貼圖。問題上限 4000 字。
- 短暫接收失敗會持續嘗試；ngrok 若中斷，按 LINE 區塊通道狀態下方的「重新連線」。通道狀態不等於外部網路端到端可達，仍需 LINE Verify。
- 通道工具停止可能需等待啟動程序完成。強制關閉終端機後若程序仍佔用連接埠，先停止舊程序。

## 故障排除

| 現象 | 檢查方式 |
|---|---|
| 開不了控制台 | 查看啟動視窗；確認 uv 可用、連接埠未被占用 |
| OpenAI 測試失敗 | 檢查 API 帳號金鑰、模型 ID、權限與用量；ChatGPT 訂閱不代表 API 設定完成 |
| LINE Verify 失敗 | 確認通道連線、完整 `/line/webhook` 路徑、LINE 已啟用及 secret 正確 |
| 收到通知卻沒報告 | 查看工作紀錄的分析或傳送錯誤、LINE 推播額度、是否仍為好友 |
| Telegram 409 衝突 | 關閉其他相同 Bot 的輪詢程序，檢查舊 Webhook |
| 憑證庫無法儲存 | 安裝可用的作業系統 backend 或用環境變數，勿把真實金鑰填入程式碼 |
| 財報或新聞缺失 | 外部服務限制、欄位缺漏或 ETF 無財報；稍後重試，不將缺項視為零 |
| 傳送結果待確認 | 先查看聊天軟體，再決定是否重新提問 |

## 開發與驗證

```sh
uv sync --locked
uv run pytest -q
uv run ruff check src tests
```

前端開發需要 Node.js，僅修改程式者需要：

```sh
cd frontend
npm ci
npm run build
```

建置輸出到 `src/stock_bot/web/`，須與 Python 原始碼一起交付。開發時可先建置後重新整理本機控制台；正式發行不依賴 Vite 開發伺服器。

詳見 [架構與 Notebook 對照](docs/architecture.md) 與 [驗收清單](docs/acceptance.md)。

模型設定提供與第五章相同的預選清單，也可自行輸入支援工具呼叫的模型 ID；請依 API 帳號可用模型選擇並測試連線。

對話輪數、工具輪數與紀錄保存參數由程式管理，不提供設定介面。每次分析最多執行 20 輪工具呼叫，再要求模型整理回答；既有分析時間上限仍適用。對話不設固定輪數，在保存期限內使用完整歷史；若模型回報上下文容量不足，會逐次移除最舊的一半問答後重試，不刪除本機紀錄。若本次問題與工具資料本身仍超出容量，會提示縮小分析範圍。


### 分析項目

「設定 → 分析項目」會套用到本機、LINE、Telegram 三種入口：

- 價格面：預設 15 個日曆天，可選 3～180 天。欄位預設為收盤價、每日報酬、漲跌價差、期間報酬，可加選成交量、MA5/20/60、RSI14、MACD(12,26,9)、布林通道(20,2)。指標使用交易日週期與原始收盤價；額外擷取 365 天暖機資料，輸出限制在選定天期。RSI 使用 Wilder 平滑，MACD 柱狀為 DIF 減訊號線（不乘 2），布林標準差使用 ddof=0。
- 基本面：預設維持營收、EPS、營收與 EPS 成長率、毛利率、營業利益率、淨利率與年報 ROE（期末權益）。可加選淨利、總資產、總負債、股東權益、營業現金流、自由現金流、市值、TTM 本益比、預估本益比及股價淨值比。季報成長率是季增率、年報是年增率；估值是來源目前快照，不是查詢天期的歷史估值。缺值不補零。
- 新聞面：預設 10 篇完整新聞，可設定 5～20 篇；來源不足或內文失敗會標示實際情況。對話明確指定時，可覆寫天期與篇數（新聞最多 20 篇）；勾選的資料欄位仍以設定為準。每個資料面的欄位至少選一項。
- 網路搜尋：預設關閉。啟用後，AI 分析改在同一次 Responses API 呼叫中提供 OpenAI 內建 `web_search`，由模型按需要搜尋補充資料；這不是爬蟲模擬搜尋。搜尋篇數與鉅亨新聞篇數分開，會增加 API / 搜尋費用。每次模型回應最多 3 次內建搜尋，外層仍受 20 輪與分析逾時限制。來源連結會附在回答；模型或帳號不支援搜尋時，本次改為不搜尋作答並在回答附註，不暗中更換模型。啟用後按「測試已儲存的模型」也會測試搜尋能力。

搜尋串接依據：[OpenAI Web search](https://developers.openai.com/api/docs/guides/tools-web-search)。財報、資產負債表與現金流來源介面：[yfinance Ticker](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html)。
