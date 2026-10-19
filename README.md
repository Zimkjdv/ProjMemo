# ProjMemo

ProjMemo 是一個以本機 Python `.venv` 執行的個人專案備註與交接清單管理工具，用來集中保存專案 URL、注意事項、已知問題、環境設定說明與交接資訊；Docker 化安排在功能接近完成後。

目前定位為個人部署、桌面使用。介面提供繁體中文與英文，可在右上角切換；瀏覽器會記住選擇，並保留目前頁面、篩選條件與內容捷徑位置。英文版沿用 `PROJECT OVERVIEW`、`REFERENCE`、`HANDOVER` 等區塊小標。專案名稱、說明、備註與標籤等使用者資料不會自動翻譯；目前 Markdown／PDF 的文件標題仍使用原本格式。

## 專案與文件

- [GitHub：Zimkjdv/ProjMemo](https://github.com/Zimkjdv/ProjMemo)
- [ROADMAP.MD](ROADMAP.MD)：待辦、已知缺口、優先級與驗收標準。
- [CHANGELOG.MD](CHANGELOG.MD)：依日期整理的已完成進度。
- [桌面 UI 設計與驗收](docs/desktop-ui.md)：目前操作規格、R06 原始規劃與實機驗收紀錄。
- [Windows 實機驗收操作](docs/desktop-acceptance.md)：獨立假資料服務、系統剪貼簿貼回及真正縮放的操作與驗收界線。
- [保管庫安全說明](docs/vault-security.md)：主密碼、salt、加密金鑰及 session 的關係。
- [本機請求保護](docs/local-web-security.md)：Host、來源、CSRF 與程式呼叫方式。
- [資料庫升級與復原](docs/database-migrations.md)：schema 版本、逐版 migration、升級前快照及失敗處理。
- [備份預覽與保留策略](docs/backup-experience.md)：還原前比較、10 分鐘確認、手動清理復原點及完整備份加密評估。
- [專案生命週期](docs/project-lifecycle.md)：封存、垃圾桶、復原、永久刪除與刪除前復原點。
- [搜尋與交接效率](docs/search-handover.md)：內容搜尋、負責人／標籤篩選、交接進度、未完成檢視與 FTS 量測決策。
- [程式架構](docs/architecture.md)：路由／服務邊界、共用資料、SQLite、請求流程及執行設定。
- [本機啟動與維運](docs/local-operations.md)、[健康檢查與安全日誌](docs/operations-health.md)：一般／開發模式、port 衝突、資料目錄與磁碟故障處理。
- [表單與驗證](docs/forms.md)：後端字數上限、網址／列舉驗證、正規化與安全回填。
- [R03 量測與分頁評估](docs/performance-r03.md)：可重跑的 SQL／HTML 量測、索引代價、鎖策略及後續 UI 分頁設計。

## 主要目標

- 集中管理個人負責的專案資訊
- 快速記錄重要 URL 與專案注意事項
- 保存 Known Issues 與 Workarounds
- 將專案內容整理成交接清單
- 一鍵匯出 Markdown 或 PDF，方便交接與寄送
- 下載 SQLite 備份，並在還原前自動保留目前資料

## 目前功能

目前已提供 URL、Markdown 備註、交接清單、環境變數說明，以及 Markdown/PDF 匯出。專案列表可切換卡片或明細清單檢視，並支援每頁 10、20 或 50 筆。

專案可由右上角「管理專案」封存或移至垃圾桶；首頁分類可切換使用中、已封存及垃圾桶。封存仍可編輯與匯出，垃圾桶保留全部內容及密文但阻擋舊網址的內容操作，復原後回原分類。永久刪除僅限垃圾桶，需完整名稱及勾選確認，且先成功建立完整 SQLite 復原點；資料備份頁可下載。這不是安全抹除，復原點及既有備份仍可能保留資料；詳見 [操作與安全界線](docs/project-lifecycle.md)。

首頁會記住已套用的檢視、筆數、搜尋範圍、負責人／標籤／交接進度及狀態篩選；明確 URL（包括空條件）優先，沒有列表參數時才還原並回到第 1 頁。可用「重設列表」回復預設，空結果的「清除篩選」則保留分類、檢視與筆數。偏好只保存於目前瀏覽器 origin，不保存專案內容、表單草稿或保管庫資料；搜尋詞最多 256 字元，請勿把密碼或 Key 當搜尋詞。禁止 storage 或不執行 JavaScript 時，原生表單與 URL 仍可使用。

基本搜尋涵蓋名稱、說明、標籤與專案負責人；可選「包含專案內容」搜尋五類紀錄的文字，**不讀取或解密密碼**，垃圾桶則限基本搜尋。進階篩選可完整比對一位負責人或一個標籤，並選尚有未完成項目／全部完成／尚無交接項目。多條件取交集，卡片／清單與 10／20／50 分頁保留條件；明細可直接前往未完成交接項目。規則、資料界線與量測見 [搜尋說明](docs/search-handover.md)。

專案內容頁也可切換卡片或明細清單，瀏覽器會記住此選擇（與首頁檢視方式分開）。明細模式依五個分類全寬排列，備註與帳號補充資料可展開；切換不會清除未送出的新增／編輯欄位，也不會自動儲存。空白分類使用精簡提示，帳號安全說明可展開閱讀。切換檢視時會立即遮蔽已顯示的密碼，並阻止尚未完成的解密請求重新顯示；既有保管庫與匯出保護保持不變。未啟用 JavaScript 時仍可使用卡片與原有表單。

建立／編輯專案採桌面雙欄排版，右側即時預覽專案卡片。負責人與標籤可用 Enter 或逗號建立徽章，支援移除與合併重複項目；未按 Enter 的最後一筆也會在送出時保存。切換語言或離開時會先確認未儲存變更；取消保留畫面，確認捨棄後不另存草稿。正式資料仍須按「建立專案」或「儲存專案」才會寫入。

內容頁的短備註在卡片完整呈現，長備註先顯示約三行摘要，可展開完整 Markdown；手動展開／收合在目前頁面跨檢視模式保留。長網址可展開查看，複製仍取完整網址；注意事項的類型與重要／關鍵優先級分開辨識。五類新增／編輯表單均有「取消並收合」：有修改時可選擇保留或捨棄，確認捨棄後才重設表單、清空敏感欄位並返回入口。切換檢視不視為取消；未啟用 JavaScript 時保留原有卡片／表單及完整文字，不提供上述增強取消保護。已提供雙語頁內錯誤與安全回填、後端欄位規則、成功提示、重送辨識及全頁離開保護；密碼不回填或寫入瀏覽器儲存，詳見 [表單說明](docs/forms.md)。

內容導覽固定於頂欄下方，五個數量徽章與各區塊標題旁的計數同時保留；經評估，重複計數有助於直接閱讀區塊時辨識數量，卡片／明細及啟用／未啟用 JavaScript 時皆保留。內容頁採較緊湊的標題與本文字級；「更多操作」始終可見，開啟與鍵盤焦點有不同強調。首頁與內容頁的檢視切換、全站語言切換也以淡藍底與邊界標明選中項目，不改首頁厚黑標題或設定頁排版。

帳號的長主機／登入名稱預設最多兩行，可展開完整原文，複製不受收合影響。明細編輯表單占用完整列，切換檢視保留草稿。備註已採真正伺服器端 10／20／50 分頁、預設 20 筆與獨立總數；無 JavaScript 也可逐頁瀏覽。局部換頁只確認備註草稿，其他區塊不重載；失敗保留原 DOM，不裁切完整匯出或備份。見 [分頁設計與量測](docs/note-paging.md)。

### 1. Project Basic Info

- 專案名稱
- 專案描述
- 專案狀態：維護中、已結案、移交中
- 專案負責人
- 標籤
- 建立時間與最後更新時間

重要 URL 類型包括：

- 正式環境
- 測試環境
- Git Repository
- Figma
- API 文件
- 其他自訂連結
- URL 可編輯與刪除

### 2. Notes & Cautions

- 支援 Markdown 格式
- 支援程式碼區塊與表格
- 可記錄一般備註、注意事項、Known Issues 與 Workarounds
- 可設定備註優先等級
- 可編輯與刪除備註

### 3. Handover Checklist

- 卡片、明細與內容頁顯示交接完成筆數／總數及剩餘項目；零項目不算全部完成
- 內容頁可切換「全部交接項目／僅未完成」，完成後不刪除資料，導覽及標題仍保留全部數量
- 備註分頁、內容表單成功／錯誤及重送保留未完成檢視；匯出與備份仍包含完整交接清單
- 帳號與權限清單
- AWS 或其他雲端權限說明
- 第三方服務與負責人
- 部署步驟
- 環境變數對照表
- 交接項目完成狀態
- 可編輯與刪除交接項目
- 補充說明與相關文件連結

### 4. Export

- 匯出單一專案為 Markdown
- 匯出單一專案為 PDF
- 匯出內容包含：
  - 專案基本資料
  - 重要 URL
  - 注意事項
  - Known Issues
  - 部署流程
  - 環境變數說明
  - 交接清單

### 5. Data Backup & Restore

- 從「資料備份」頁面下載完整 `.sqlite3` 資料庫快照
- 可還原先前下載的 ProjMemo 備份；還原前會檢查 SQLite 完整性、必要資料表、欄位及關聯資料
- 還原先預覽目前／備份的版本、各類筆數、保管庫與匯出政策；不立即替換。勾選並輸入 `RESTORE` 才確認；10 分鐘過期、重啟、其他瀏覽器或預覽後資料變更會拒絕，須重新預覽
- 替換前會驗證八張業務表、遷移紀錄（v2 起）、必要索引（v3 起）、型別、關聯與保管庫參數；兼容沒有保管庫表的舊版備份，拒絕不完整結構與未知版本。還原後初始化及驗證失敗會自動回復原資料
- 還原會等既有作業完成，期間的新資料請求及第二次還原回覆 503，請稍後重試；這個保護限單程序，仍須使用單 worker
- 自動回復若失敗，一般資料存取會被阻止，但備份頁與還原前備份仍可下載。請依 [復原操作指南](docs/backup-recovery.md) 停止程式後復原
- 每次還原前會自動保留一份可下載的還原前備份
- 還原上傳限制為 100 MB
- 還原前備份保存在目前資料庫所在目錄的 `backups/` 子目錄，最多顯示最近 10 份且不會自動刪除
- 可自訂復原點保留份數與最短天數；預設全部保留，不定時刪檔。清理須先預覽檔名、下載需要的副本，再勾選並輸入 `DELETE`；只刪列出的檔案，至少保留一份驗證通過的復原點。遷移快照、正式 DB 及未知檔案不在清理範圍
- 保留政策在 `backups/retention-policy.json`，不隨 SQLite 還原覆寫；完整備份加密目前只有評估，下載仍是含明文專案資料的 SQLite。詳見 [備份操作與安全界線](docs/backup-experience.md)
- 啟動／還原時會將已支援的舊 schema 逐版升級；升級前快照另存於 `backups/migrations/`，不列入還原前備份清單，也不會自動刪除。遷移或復原失敗時停止該次初始化，見 [資料庫升級與復原](docs/database-migrations.md)

### 6. 帳號與密碼保管庫

- 可記錄資料庫、網站測試帳號、主機、雲端及第三方服務的帳號資訊，並關聯環境、端點、權限範圍、用途與負責人
- URL、主機／登入網址、登入帳號及 Markdown 程式碼區塊可複製完整原始文字；剪貼簿不可用時保留文字供手動複製，沒有實際密碼複製功能
- 專案與保管庫頁顯示本次解鎖剩餘時間／到期時刻，重新載入不延長；到期遮蔽並停用密碼操作，跨分頁通知或定期重查後保持一致，非敏感草稿保留
- 保管庫只支援單程序、單 worker；重複解鎖撤銷舊 token、定期清理過期項目，安全界線見 [保管庫安全說明](docs/vault-security.md)
- 實際密碼以主密碼派生的金鑰使用 AES-GCM 加密後存入 SQLite；資料庫不保存明文密碼或主密碼
- 只有實際密碼欄位加密；帳號名稱、登入名稱、主機、用途、專案備註等一般資料不加密
- 主密碼至少 16 個字元；忘記主密碼後無法解密既有密碼，也沒有重設或後門
- 解鎖金鑰暫存在應用程式記憶體，session 有效期限為 15 分鐘，重啟後失效；這不等於到期瞬間即保證安全抹除記憶體，詳見保管庫安全說明
- 密碼只有在使用者主動解鎖後才可短暫顯示；切換離開瀏覽器分頁會立即遮蔽
- 一般 Markdown／PDF 匯出永遠不含實際密碼；保管庫設定預設禁止敏感匯出
- 如確有需要，可在設定中允許額外的含密碼匯出；每次仍須解鎖並勾選確認，產生的文件會標示為敏感資料
- SQLite 備份中的實際密碼為密文，其他專案及帳號欄位仍為明文；還原密碼資料必須使用原主密碼
- 此保管庫是本機個人用途的便利功能，不應取代組織核准的密碼管理工具；避免保存高權限正式環境密碼
- ProjMemo 目前沒有登入與多使用者權限，請勿將服務公開到區域網路或網際網路

## 目前資料模型

### Project

- `id`
- `name`
- `description`
- `status`
- `owner`
- `tags`
- `created_at`
- `updated_at`

### ProjectUrl

- `type`
- `title`
- `url`
- `note`

### Note

- `category`：`note`、`caution`、`known_issue`、`workaround`
- `title`
- `content_markdown`
- `priority`

### ChecklistItem

- `category`：帳號、部署、環境、服務
- `title`
- `description`
- `owner`
- `completed`
- `note`

### EnvironmentVariable

- `key`
- `environment`：local、staging、production
- `description`
- `source_or_owner`
- `is_secret`

環境變數區只記錄設定用途、套用環境及 Secret 的存放位置或負責人，不提供 Secret 值欄位。帳號與登入密碼請另存於加密保管庫。重要 URL 與環境變數也可編輯或刪除。

### AccessAccount、VaultConfig、AppSettings

- `access_accounts`：所屬專案、類別、環境、端點、資料庫名稱、登入名稱、權限、用途、負責人、保管位置及密碼密文／nonce。
- `vault_config`：salt、加密驗證資料及 Argon2id 參數；不保存主密碼或解密金鑰。
- `app_settings`：是否允許額外的敏感匯出，預設關閉。

實際 schema 與逐版定義以 `app/migrations.py` 為準，由 `app/db.py` 管理交易、快照與失敗復原。`PRAGMA user_version` 現為 **4**：八張業務表、`schema_migrations` 紀錄表、七個量測索引與生命週期索引。v4 追加封存／垃圾桶時間與確認用 revision，不改既有 ID 或密文。支援 v0（完整五表或八表）、v1／v2／v3 升級；紀錄自 v2 起保存名稱與 UTC 執行時間，不補造 v1 歷史。已是最新版時不重複套用、不新增快照；版本／紀錄／結構或必要索引不符則拒絕啟動或還原。操作與限制見 [資料庫升級與復原](docs/database-migrations.md)。

寫入服務會先預留 SQLite writer，SQL 鎖等待明確為一秒；忙碌時回滾並回覆 503／Retry-After，不自動重送資料。備份 API 另限制連續鎖等待，不限制健康複製的總時間。索引不改變資料排序、保管庫加密或完整匯出；備註伺服器端分頁與 R05 草稿保護已交付，畫面只讀當頁，匯出仍讀全部資料。見 [量測、代價與設計](docs/performance-r03.md)。

## 技術方向

- Backend：FastAPI
- Architecture：`app/main.py` 組裝應用，`routers/` 處理 HTTP、`services/` 管理交易與業務；共用 `ProjectData` 與列舉供 UI／Markdown／PDF 使用
- Initial UI：Jinja2 + HTML/CSS
- Database：SQLite
- Local runtime：Python `.venv`
- Later deployment：Docker Compose
- 文件格式：Markdown
- PDF：ReportLab 產生 A4 文件

PDF 匯出會包含專案資料、重要 URL、備註中的 Markdown 內容、環境變數說明及交接清單，並加入頁首、頁尾與頁碼。繁體中文字型會自動尋找作業系統字型（Windows 優先使用 Microsoft JhengHei；Linux 可安裝 Noto Sans CJK）。如需指定字型，可設定 `PROJMEMO_PDF_FONT`；粗體字型可選用 `PROJMEMO_PDF_BOLD_FONT`。

目前先以本機 `.venv` 執行，確認資料模型與使用流程接近完成後，再進行 Docker 化。第一版不急著導入 MySQL、複雜權限或多使用者架構。未來若需要多人協作，再考慮切換至 PostgreSQL 或 MySQL。

## 本機開發

Windows x64 首次安裝或明確更新依賴時執行（目前支援 CPython 3.12 與 Windows `py` launcher）：

```bat
setup-local.bat
```

日常啟動不安裝或升級套件，可從其他工作目錄呼叫完整腳本路徑：

```bat
run-local.bat
```

只檢查環境、不啟動服務或開啟資料庫：`run-local.bat --check`。缺少 `.venv`／依賴會顯示修復指引並以非零代碼結束，不會自動連網安裝。安裝腳本也會檢查 venv／pip／依賴失敗，不在失敗後繼續啟動。

或手動執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m app.launcher --dev
```

### `run-local.bat` 與 `run-dev.bat` 的區別

| 項目 | `run-local.bat` | `run-dev.bat` |
| --- | --- | --- |
| 適用情境 | 日常使用，避免開發重載中斷操作 | 開發、頻繁修改程式 |
| 修改 Python 程式後 | 不自動重載，須停止服務再啟動 | 偵測 `app/` 內的 Python 檔案變更並自動重啟 |
| 執行環境 | 專案的 `.venv`，不自動安裝或升級套件 | 與一般模式相同 |
| 資料庫 | 預設使用 `data/projmemo.db` | 與一般模式相同，不是獨立測試資料庫 |
| 保管庫與表單 | 手動重啟後，保管庫解鎖狀態與舊表單 token 失效 | 自動重載或手動重啟後，同樣失效 |

`run-dev.bat` 實際上會呼叫 `run-local.bat --dev`。日常使用選一般模式；持續調整程式時可選開發模式。兩者的差異是服務是否自動重載，不是功能或資料隔離。

使用 `run-local.bat` 時，更新程式後請先用 `Ctrl+C` 停止舊服務，再啟動；**只有重新整理瀏覽器，不會載入新版 Python 程式**。開發重載也不代表所有檔案變更都會自動生效；更新依賴或啟動腳本後，仍須停止服務，依需要執行 `setup-local.bat`，再重新啟動。

兩者固定 `127.0.0.1`、單 worker，從 `8000` 起實際綁定可用 port 並持有 socket 交給服務，不再使用先探測後釋放的方式。衝突時最多嘗試 100 個 port，終端機顯示實際網址；全部不可用時非零結束。可用 `--port 8123 --port-end 8130` 限定範圍，不開放 LAN host／多 worker 選項。本機 SQLite 預設在 `data/projmemo.db`，已加入 `.gitignore`。

啟動及安裝 batch 會固定切換至自己的目錄；手動 Python 指令仍請從專案根目錄執行。重啟或重載前請先儲存未完成的內容；完成後重新整理頁面，並視需要重新解鎖保管庫。**不要同時啟動兩份服務共用同一份資料庫**；切換模式時先停止原本服務。開發模式有監督程序與一個應用 worker，不是多 worker 部署。不要用手動 Uvicorn 指令繞過本機／單 worker 限制，詳見 [本機維運](docs/local-operations.md)。

可用 `PROJMEMO_DB_PATH` 指定另一個 SQLite 路徑；PDF 字型可由 `PROJMEMO_PDF_FONT`、`PROJMEMO_PDF_BOLD_FONT` 指定。更換資料庫前請先停止程式並備份。

若要手動指定 port：

```powershell
$env:PROJMEMO_PORT = "8123"
python -m app.launcher
```

## 測試

[GitHub CI 與檢查規範](docs/ci.md)：push／PR 預設只跑 Windows baseline；Linux／CJK 需手動 Run workflow 勾選 `run_linux` 且 Windows 成功後才執行，使用相同依賴鎖。2026-10-16 已完成 PDF glyph 修正後的兩平台完整補驗，手動 gate 保留；skipped 不算該次驗收通過。本機可先執行 `python scripts/check_sources.py`。CI 不部署、不上傳資料庫。

雙語維護可執行 `python scripts/check_catalogs.py`；新增 UI 文字、動態訊息、unused key 與佔位符規範見 [catalog 維護](docs/localization.md)。Markdown 特殊字元與投影回歸見 [匯出契約](docs/markdown-export.md)。

真實桌面瀏覽器另有獨立 npm 開發鎖與 [瀏覽器回歸指南](docs/browser-regression.md)：Chromium／Firefox，Windows CI 另驗證已安裝 Edge；每例自行建立隔離 DB 與空閒 loopback port，不連目前使用的服務。原生／JS、雙語表單及備份流程均可重跑；不代替 R06 的系統剪貼簿或真實 Windows 縮放驗收。

真實 PDF 的生成、抽字、CJK／邊界與逐頁渲染見 [PDF 驗收指南](docs/pdf-verification.md)，含可重跑假資料工具。額外 PDF 工具僅在測試鎖，日常 runtime 不需要 pypdf／PDFium／Poppler；一般匯出仍不含密碼。

日常 setup 只裝根目錄 `requirements.txt` 的 runtime；人工需求、測試鎖與維護工具清單集中在 `requirements/`，沒有合併到正式安裝。開發測試先執行 `.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements/requirements-test.txt`，再執行 `.\.venv\Scripts\python.exe -m pytest tests -q`。若有安裝 Node.js，完整前端檢視、分頁、表單與密碼遮蔽測試可執行 `node --test tests/js/*.test.cjs`；Node.js 只用於開發測試，並非應用程式執行需求。架構邊界、HTTP 契約及交易回滾另有 `tests/test_architecture.py`；使用隔離 DB，初始化不得指向正式資料。套件鎖定、更新／離線重建與漏洞掃描見 [依賴維護](docs/dependencies.md)。

## 安全原則

環境變數與一般備註不應直接保存密碼、API Key 或其他 Secret。建議只記錄：

- Secret 的存放位置
- 申請或取得方式
- 負責人
- 使用環境
- 相關文件連結

如使用帳號與密碼保管庫，請使用唯一且難以猜測的主密碼並妥善保存；任何拿到 SQLite 檔案的人都能看到非密碼專案資料及密文，密碼內容則仍需要正確主密碼才能解密。敏感匯出可能留下可讀取密碼的檔案副本，預設不啟用。

## 開發進度

已完成的階段紀錄移至 [CHANGELOG.MD](CHANGELOG.MD)，未完成項目統一維護於 [ROADMAP.MD](ROADMAP.MD)。R09 已提供封存、垃圾桶、復原及先快照再永久刪除；R10 已提供獨立標籤／負責人篩選、內容搜尋與交接進度；R11 已提供還原前比較及明確確認、自訂復原點保留策略與手動清理。完整備份加密僅完成評估，實際功能另列 Later。

P0、R03／R04／R05／R06／R07／R08 已完成。R08 的 Markdown、catalog、CI、真實瀏覽器互動與真實 PDF 生成／抽字／渲染／Windows 視覺驗收已交付；PDF 字型修正後的 Linux／CJK 雲端補驗，以及 R06-B 的實際 Windows 系統剪貼簿手動貼回與雙語失敗回饋，亦於 2026-10-16 通過。R06 另外完成 Windows Chrome 真正 125%／150% 的 72 組版面、120 組表單、鍵盤／長文與人工錨點確認，最後還原原本 100%；原驗收文字及方法見 CHANGELOG 與實機指南，不以等效寬度或工具虛擬剪貼簿代替。套用新依賴前先停止舊服務，再執行一次 `setup-local.bat`，日常用 `run-local.bat`。Docker 待本機功能穩定後另行安排；多人協作與手機排版不屬於目前個人版範圍。
