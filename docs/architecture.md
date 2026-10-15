# ProjMemo 程式架構

目前定位：本機 `.venv`、FastAPI／Jinja2／原生 JavaScript、SQLite、單程序個人桌面版。這份文件描述現行程式，不是多人協作或 Docker 部署設計。

## 模組邊界

```text
app/main.py：create_app()、lifespan、middleware 與錯誤處理
  └─ routers/：projects、content、accounts、vault、backups、exports、language
       ├─ presentation.py：模板、繁中／英文 context、安全 Markdown、轉址
       └─ services/：projects、content、accounts、vault、backups、exports
            ├─ db.py／database_access.py：交易與程序內排他作業
            ├─ vault.py：密碼學、session 與限流原件
            ├─ backup.py：SQLite 備份／還原與失敗回復
            └─ markdown_export.py／pdf_export.py：文件產生器

共用：options.py、project_data.py、errors.py、runtime.py
```

| 模組 | 責任與限制 |
| --- | --- |
| `main.py` | 組裝 app、掛載 static／七個 router、全域 CSRF 依賴及錯誤處理；啟動先遷移，再每 30 秒清理 session，停止時取消清理工作。不放 SQL／表單業務邏輯。 |
| `routers/` | 保留既有 URL、參數、表單預設值及回應格式。讀取 Request／cookie，呼叫服務，處理 HTML／JSON、下載、303 及安全 cookie／header；不執行 SQL 或自行提交交易。 |
| `services/projects.py` | 專案搜尋、列表／分頁資料、基本資料修改、完整專案查詢及共用 `touch_project()`。目前仍載入完整內容，不是內容的伺服器端分頁。 |
| `services/content.py`／`accounts.py` | 內容驗證、資料修改與專案更新時間在同一交易內；帳號 ID 先建立再加密，失敗整筆回滾。reveal 在解密前及回傳前檢查解鎖，避免到期後回傳明文。 |
| `services/vault.py` | 設定／解鎖、限流、session 操作與敏感匯出政策；保留既有錯誤碼。底層 Argon2id／AES-GCM 與 AAD 仍在 `app/vault.py`，本次不改。 |
| `services/backups.py` | 頁面資料、暫存上傳、還原流程與 session 撤銷、恢復檔案路徑檢查。`backup.py` 保有 SQLite 級驗證、快照、排他與回復。上傳 HTTP 檔案由 router 關閉，暫存 DB 由服務清理。 |
| `services/exports.py` | 普通／敏感匯出的資料載入、政策及文件產生，回傳 `ExportArtifact`；路由才加下載 header。兩種格式共用完整 `ProjectData`，不受畫面分頁限制。 |
| `options.py` | 單一份狀態、類別、優先級與環境列舉，以及既有匯出用標籤。頁面透過 `presentation.py` 翻譯；使用者內容和既有匯出文字不自動翻譯。 |
| `project_data.py` | `ProjectData` 定義專案與五類內容，提供模板 context 與 Markdown／PDF 相同的參數順序。普通查詢只回傳帳號 metadata／`has_secret`，不含密文、nonce 或明文。敏感匯出另外授權／查詢，以新的 projection 取代帳號清單，不污染普通資料。 |
| `errors.py` | `ApplicationError` 僅保存既有狀態碼與訊息；服務不依賴 FastAPI／Request／Response。入口將它轉成原本雙語、禁止快取的 HTTP 錯誤；保管庫表單在 router 顯示原有 HTML 錯誤。其他表單的頁內回饋仍屬 R05 待辦。 |
| `runtime.py` | 每個 app 的 `AppRuntime` 保存自己的 `VaultSessions`／`UnlockAttemptLimiter`，不再借用 `main.py` 的全域變數；不是使用者登入，也不是多人權限系統。 |

正式入口仍是 `app.main:app`，啟動方式不變。`create_app(runtime=None)` 方便隔離測試及依賴替換；建立 app 不會連線或建立 DB，真正初始化在 lifespan。

## 一次內容修改的流程

1. `LocalRequestSecurityMiddleware` 檢查本機 Host／來源及 Fetch Metadata；`DatabaseAccessMiddleware` 協調一般作業與還原。
2. 全域 `require_csrf` 驗證所有寫入路由，FastAPI 解析既有表單型別；router 不增加安全繞過開關。
3. router 呼叫服務。服務執行既有空值／enum／URL 等驗證，開啟 `db_session()`，讀取所屬專案或內容。
4. 同一連線修改內容並呼叫 `touch_project(connection, project_id)`，由 `db_session()` 一次 commit；包括專案時間在內，任何一步例外都 rollback。基本資料修改的欄位與時間仍在同一 UPDATE。
5. router 依原有方式回傳 303、頁面、JSON 或下載。頁面共用 context 與 Markdown HTML 清理，不把密碼插入 HTML。

還原／恢復下載是特殊流程：備份頁及還原前檔案保留存取能力，還原本身取得排他權，等待已接納作業完成，再快照、撤銷解鎖、替換、遷移及驗證。請遵循 [備份與復原操作](backup-recovery.md)，不要用一般內容交易包住還原。

## SQLite 資料模型

現行 schema **v2**：八張業務表、一張遷移紀錄表。`projects.id` 是下列五類內容的父項，外鍵刪除規則為 CASCADE；目前沒有專案永久刪除路由。

| 表 | 內容 |
| --- | --- |
| `projects` | 名稱、說明、狀態、負責人、標籤與建立／更新時間。 |
| `project_urls` | 專案連結的類型、名稱、URL、說明。 |
| `notes` | 類別、優先級、標題、Markdown 本文。 |
| `checklist_items` | 交接類別、內容、負責人、完成狀態及備註。 |
| `environment_variables` | 變數名稱、環境、用途、Secret 位置／負責人；不保存變數實際 Secret 值。 |
| `access_accounts` | 帳號 metadata；只有實際密碼以 `secret_ciphertext`／`secret_nonce` 加密保存。 |
| `vault_config` | 單筆 salt、驗證密文、nonce 與 KDF 參數；不保存主密碼或解密金鑰。 |
| `app_settings` | 單筆敏感匯出政策，預設關閉。 |
| `schema_migrations` | 自 v2 起的版本、固定名稱、UTC 套用時間；與 `PRAGMA user_version` 一致。 |

完整欄位定義在 `app/migrations.py`。`app/schema_validation.py` 供啟動／還原共用，`app/db.py` 負責逐版交易、升級前快照與錯誤復原。細節見 [SQLite 結構升級與復原](database-migrations.md)；本輪服務拆分不提高版本、不加索引、不切換 WAL 或重寫密文。

## 執行設定與安全界線

| 設定 | 使用方式 |
| --- | --- |
| `PROJMEMO_DB_PATH` | 由 `db.py` 讀取，預設為專案根目錄下 `data/projmemo.db`；相對路徑依目前工作目錄解析，因此建議使用絕對路徑。切換前先停止程式並備份。 |
| `PROJMEMO_PORT` | `run-local.bat` 使用；未指定時從 8000 探測空閒 port。直接啟動 Uvicorn 仍須用 `--port`，它不會自動讀取此設定換 port；探測到綁定之間仍可能競爭，屬 R07 待辦。 |
| `PROJMEMO_PDF_FONT`／`PROJMEMO_PDF_BOLD_FONT` | 指定 PDF 的 CJK 字型；未指定時依作業系統候選字型尋找。Windows 候選位置使用系統 `WINDIR`（缺少時為 `C:\Windows`）。 |

維持 `127.0.0.1`、**單程序／單 worker**。AppRuntime 隔離只代表不同 app 不共用解鎖與限流物件；DB 路徑仍由程序環境設定，DB 排他 registry 和 CSRF 簽章也有程序範圍，不能據此宣稱多租戶、任意多 app 共用 DB 或多 worker 安全。

主密碼僅用於當次金鑰派生與驗證，解鎖金鑰保留於 app 記憶體 session；cookie 僅保存不透明 token。來源／CSRF 規則及 15 分鐘安全界線維持原設計，詳見 [本機請求保護](local-web-security.md)、[保管庫安全說明](vault-security.md)。`--reload` 重載及程式重啟都會使解鎖失效。資料目錄、快照與敏感輸出不得提交 Git。

## 測試與後續修改

- `tests/fixtures/http_contract.json` 固定來自 `45369b5` 重構前的 HTTP 契約；比對 URL／method、operation ID、查詢／表單欄位、預設值及回應 schema。測試不自行更新此基準，真的改 API 時才人工審查。
- `tests/test_architecture.py` 檢查邊界、共用列舉、app 狀態隔離、16 種內容操作的交易回滾／時間更新、加密失敗回滾及完整／不解密的普通匯出。
- 依賴替身應套在實際擁有者：PDF 在 `app.services.exports.generate_project_pdf`，reveal 解密在 `app.services.accounts.decrypt_secret`，還原初始化／快照流程在 `app.services.backups`；不要重新匯入 `main.py` 當服務定位器。
- 測試先以 `PROJMEMO_DB_PATH` 指向隔離資料庫，再進入 app lifespan；不得用正式 DB 驗證。完整執行 Python 與 Node 測試，舊版 migration、備份回復與加密 AAD 仍要一起回歸。
- 本輪已用相同測試資料、固定 ReportLab 非內容時間資訊，確認重構前後普通／敏感 Markdown 與實際 PDF 輸出一致。這不是跨平台字型或全部長表格／視覺排版的驗收，R08 PDF 完整驗收仍保留。

查詢／索引量測、內容伺服器端分頁、R05 表單回饋、CI 與啟動維運仍見 [ROADMAP.MD](../ROADMAP.MD)。未因這次模組拆分而改成 Docker、多人或手機版。
