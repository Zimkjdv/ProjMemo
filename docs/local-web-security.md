# 本機 Web 請求保護

目前只有本機個人版，沒有登入或多人權限。Host 檢查與 CSRF 不等於使用者認證；不要把服務公開到區域網路或網際網路，並使用單 worker。

## 瀏覽器操作

- 允許 `127.0.0.1`、`localhost`、`[::1]`，可搭配合法的動態 port；啟動腳本綁定 `127.0.0.1`。自訂主機名稱及區網 IP 不在白名單。
- POST 等修改操作的 Origin／Referer（有提供時）必須與實際 Host、scheme、port 完全對應；不同 port 即為不同來源。Fetch Metadata 為 cross-site／same-site 時拒絕。`Origin: null` 等不明來源也拒絕。
- 頁面帶有簽章 CSRF token 與 HttpOnly／SameSite=Strict cookie。所有 POST 路由都需驗證；一般表單內有隱藏欄位，無 JavaScript 也可使用。顯示密碼的 fetch 請求以 `X-CSRF-Token` 傳送。
- token 放在 DOM，不放進網址或瀏覽器 localStorage／sessionStorage；它不是主密碼、保管庫 session 或解密金鑰。重新啟動後舊頁 token 失效，403 時請重新整理頁面再操作。
- 部分 sandbox 內嵌瀏覽器會把 Origin 送成 `null`，即使顯示本機網址也會被拒絕；請以標準桌面瀏覽器直接開啟終端機顯示的本機網址。不可為了內嵌工具而放行不明來源。

HTML 頁面及備份下載使用 `no-store`；備份仍需妥善保存，下載的 SQLite 不是整檔加密。禁止 framing 與 nosniff 等標頭不代表完整的 CSP／XSS 防護，Markdown 的既有清理仍須維持。

## 程式呼叫

現有腳本需要先 GET 一個 HTML 頁面（例如 `/projects/new`），保存 cookie，從頁面的隱藏 `csrf_token` 或 meta 標籤取得 token。POST 時同時帶原 cookie 與以下其中一項：

- 表單欄位 `csrf_token`（含 multipart 備份上傳）。
- Header `X-CSRF-Token`（例如帳號密碼 reveal）。

如果設定 Origin，必須是同一個 scheme／host／port；不要偽造來源或抹除瀏覽器安全標頭來繞過驗證。API 呼叫本身不取代保管庫解鎖及敏感匯出的既有確認。

## 設計參考與驗證範圍

採用簽章 double-submit token、來源及 Fetch Metadata 多層檢查，參考 [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)。共同路由驗證使用 [FastAPI Global Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/global-dependencies/)，避免新增路由時漏接。

隔離回歸涵蓋 token 缺失／偽造／過期、Host、來源、雙語、動態 port、原生表單、multipart 還原與禁止快取；另以實際 HTTP 與瀏覽器驗證跨 port 拒絕。此範圍不是多使用者認證或完整滲透測試。
