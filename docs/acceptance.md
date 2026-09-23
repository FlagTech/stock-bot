# 驗收清單

## 不需真實帳號

- Windows 啟動入口與双連接埠可啟動。
- 控制台首頁、試聊、設定、平台串接、工作紀錄、指南可切換。
- `/help` 無金鑰可完成；未設定 AI 的問題顯示中文錯誤。
- Host / Origin / CSRF 防護、公開 Webhook 無管理 API。
- 簽章驗證、空驗證事件、重複 LINE 事件。
- Telegram 既有 Webhook 衝突、接收 offset 持久化。
- 相同會話依序執行、不同會話隔離、重啟後工作標記。
- Emoji 訊息分段、LINE 相同 retry key、Telegram 不確定傳送。
- AI 工具流程以模擬客戶端驗證，包含工具參數限制。
- 欄位順序變化、缺項、原始 Close 報酬口徑；與 Adj Close 不同時仍使用 Close。
- 不截斷當日資料、標示當日數值可能未定案、無當日資料時顯示最後可用日期。
- 新聞結構化內文、正文段落備援、單篇失敗保留來源且不中止其他篇。

## 需由讀者填入真實金鑰後驗收

目前不將模擬測試視為下列串接已通過。

1. OpenAI：填入自己的模型與金鑰，連線測試成功；股票問題可調用真實模型工具。
2. LINE：取得權杖與 secret，ngrok 啟動取得 HTTPS 網址，LINE Verify 成功。
3. LINE：私人訊息可收到接收通知與完整推播；長回覆分段；用量足夠。
4. Telegram：建立 Bot，測試成功、/start、股票提問與 /reset 均完成。
5. 同時啟用兩平台：脈絡互不混用；停止與重新啟動不重複回答舊事件。
6. macOS：uv 安裝、Keychain 金鑰保存、啟停與通道程序回收。
7. 實際的斷網、平台限流與額度不足情境，對照控制台中文提示。

API 規格參考：

- https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
- https://developers.line.biz/en/reference/messaging-api/
- https://core.telegram.org/bots/api
- https://ngrok.com/docs/pricing-limits/free-plan-limits
