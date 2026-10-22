# ProjMemo 深度稽核與安全清理計畫

日期：2026-10-22（Asia/Taipei）。稽核基準：`813a081bab9c34deab25cf9e9f76670f026abdcd`。

依據：[六階段稽核規範](../prompts/SAFE_CODEBASE_AUDIT.md)。本報告是分析與待審核計畫，不是清理授權。

本次批准範圍僅有：新增本報告，並將本報告及既有提示原檔 commit／push。**沒有批准修改或刪除程式、測試、設定、依賴、快取、資料或備份。** 原提示內容不修改；不更新 Roadmap／Changelog，也不把以下候選勾選為已完成。

## 第一階段：理解專案與建立邊界

### 產品、架構與相容性

- 個人部署、桌面操作、Windows CPython 3.12／`.venv`、SQLite；不是多人協作或公開網路服務。Docker、完整備份加密、Mermaid 圖形渲染及 R14 仍屬有條件後續工作。
- FastAPI 組裝於 [main.py](../app/main.py)，九個 router、八個 service；Jinja2／原生 JavaScript 提供增強操作，無 JavaScript 的表單與分頁仍是有效產品行為。
- schema v4 必須保留 v0 五表／八表及 v1–v3 升級、遷移歷史、升級前快照、交易失敗回復與不安全狀態阻擋。不能以「舊版本」為由刪除。
- 一般頁面與匯出不讀取實際密碼；敏感匯出另外要求政策、解鎖與確認。Argon2id、AES-GCM、AAD、密文格式與原主密碼的關係不在清理範圍。
- [HTTP 契約快照](../tests/fixtures/http_contract.json) 及 [架構測試](../tests/test_architecture.py) 是相容性承諾，不能重新產生快照來掩蓋變更。
- 依據為 [README](../README.md)、[Roadmap](../ROADMAP.MD) 與架構／安全／備份／維運文件。根目錄未發現 `AGENTS.md`、`REQUIREMENTS.md` 或 `AGENTS-MAINTENANCE.md`，不虛構這些檔案的規定。

### Git 與檔案基準

- 開始時為 `main...origin/main`，沒有已追蹤檔案的 staged／unstaged 變更，只有使用者提供的 `prompts/SAFE_CODEBASE_AUDIT.md` 尚未追蹤。
- 對 223 個已追蹤檔案及提示原檔共 224 個檔案建立記憶體中的 SHA-256 基準。完成唯讀調查、撰寫本報告之前再次比對，224 個原檔內容均未變動；沒有另外建立雜湊清單檔。
- 稽核前半段 Git 讀取使用 `GIT_OPTIONAL_LOCKS=0`；只有使用者後續明確批准的文件發布階段才允許暫存、提交及 fetch／push。
- 原有正式 launcher 正在使用專案 `.venv`；沒有停止服務、讀取實際 DB／備份內容、讀取 `.env`／密碼，或操作使用者瀏覽器。

### 動態與間接入口

- ASGI 入口 `app.main:app`、`create_app()`／lifespan、全域 `Depends(require_csrf)`、`MutationRoute`、middleware 與背景 session／預覽清理。
- [launcher.py](../app/launcher.py) 的動態匯入及 Windows 重載 adapter；不能僅查直接 Python import 判斷依賴是否無用。
- 主 router 之外，[vault.py:107–120](../app/routers/vault.py#L107) 另有 `password_router` 並 include 至主 router。補查這層後，來源宣告共有 53 組不同 method／path（16 GET、37 POST）；不是執行時路由列舉，也不包含 FastAPI 自動文件及 static mount。
- Jinja globals／filters／include、Markdown extension 名稱、PDF 字型環境設定、前端 `data-*`／自訂事件／局部載入重新綁定、列舉與文件 catalog，均有非直接呼叫用途。
- 保留 `/settings/backup/restore` 舊程式呼叫入口、舊一鍵 Markdown／PDF 匯出與新選項入口；外部消費者沒有被完整盤點，不能因新 UI 已換入口就直接刪除舊 API。

## 第二階段：深度盤點與交叉調查

### 覆蓋範圍

版本控制盤點包含 50 個應用 Python 檔、22 個模板、21 個靜態資源、42 個 `test_*.py`、16 個 Node 測試檔、8 個瀏覽器 spec，以及 25 個 docs 檔案。數量是檔案盤點，不代表每一個測試函式都完成逐行語意審查。

三個不重疊的唯讀分工分別檢視核心資料／安全、前端／資源、測試／依賴／維運；主線另核對專案／匯出服務、HTTP 與間接入口、文件一致性、本機產物及候選證據。所有分工均未編輯檔案、執行測試、啟動服務或匯入 app；候選由主線交叉確認後才列入本報告。

### 整體判斷

目前沒有證據支持大規模刪除模組、依賴或整份測試。較可靠的整理收益是少量失效 CSS、重複初始化掃描、未使用的測試 import、現行文件措辭，以及可選的測試 helper 共用。

舊前端分頁存在退役機會，但仍有直接測試及對外 static 路徑；核心 authorizer 雖重複，卻同時保護 migration 與密碼重加密。這些不能和低風險文字整理混成同一批。

另發現兩項應獨立審查的正確性／維運風險。以下「風險」表示可能影響及修改所需保護程度，不是 CVE 評級，也不表示已證明遠端可利用。

## 第三階段：證據與風險評估

### R01：復原點建立與讀取的目錄連結政策不一致

**高風險；優先安排隔離重現與修正提案，不在本輪修正。**

- 位置：[backup.py:120–147](../app/backup.py#L120) 的 `create_deletion_snapshot()`／`create_vault_change_snapshot()`／`_create_reserved_snapshot()`；[backup.py:163–167](../app/backup.py#L163) 的還原前快照；[backup_retention.py:19](../app/backup_retention.py#L19) 的 `safe_directory()`；[services/backups.py:83](../app/services/backups.py#L83) 的下載路徑檢查。
- 直接證據：更換主密碼前明確拒絕 symlink／junction；刪除及還原前建立快照沒有同樣的建立前檢查。列出／下載復原點則拒絕連結目錄。泛用快照 helper 的來源／目的地不同檢查不能代替目錄連結政策。
- 推論與未驗證：若 `backups/` 是連結，部分破壞性操作可能完成，但 UI 無法列出或下載該復原點。本輪沒有檢查正式備份位置，也未建立連結重現；不能宣稱已造成資料遺失或遠端漏洞。
- 引用追蹤：刪除由 `services/lifecycle.py` 呼叫，還原由 backups service 呼叫；現有 [目錄拒絕測試](../tests/test_backup_retention.py#L180) 只直接驗證 `safe_directory()`，不能證明三個快照入口都受保護。
- 收益／最壞影響：統一操作前提，避免事後無法從既有 UI 取得復原點；修正也可能拒絕使用者原本透過 junction 安排的儲存配置，因此須明確說明政策，不能偷偷放寬下載保護。
- 未來驗證／回復：以隔離資料驗證刪除、還原、更換主密碼三入口在 symlink／junction 下均於修改或撤銷 session 前拒絕，並比對 DB、session、連結目標及普通目錄成功流程。Windows 真正 junction 另驗；本項不自動擴充成重寫 migration 快照。回復僅撤回獨立程式修補，保留所有 DB 與快照，不降版資料。

### R02：備份警告未接上應用程式自有檔案 logger

**中風險；獨立維運修正候選。**

- 位置：[operations.py:76–93](../app/operations.py#L76) 的 `operational_log()`；[backup_plans.py:38](../app/backup_plans.py#L38) 與 [backup_activity.py:61](../app/backup_activity.py#L61)。
- 直接證據：前者直接建立每 app 擁有的 `logging.Logger("projmemo.operations")` 及 rotating handler；後兩者從全域 logging registry 取得 logger。相同名稱不等於同一物件，組裝未見橋接，這些警告不會因此自動交給該 app 自有的檔案 handler。
- 引用與缺口：既有 metadata 故障測試檢查 `caplog`；預覽清理測試檢查重試與容量，沒有證明兩種警告寫入 app 的 `projmemo.log`。外部 logging 設定仍可能收錄，不應說成「警告完全消失」。
- 收益／最壞影響：讓 metadata 及暫存刪除失敗可追查；不當改接全域 logger 會造成跨 app 混流、重複記錄或 handler 洩漏。不要只把 app 自有 logger 換成全域物件來掩蓋差異。
- 影響範圍：不需改 DB 格式、下載 API 或把原始例外／敏感欄位寫入日誌。
- 未來驗證／回復：設計明確的安全記錄介面；故障注入確認固定代碼落檔、下載仍成功、無敏感值、多 app 不混流且停止關閉 handler。回復僅撤回記錄介面的接線。

### A01：失效與重複 CSS 宣告

**低風險；可優先的小批整理。**

- 位置：[styles.css:343](../app/static/styles.css#L343)、[359](../app/static/styles.css#L359)、[860](../app/static/styles.css#L860)、[876](../app/static/styles.css#L876)。
- 證據：較早 `.secret-badge` 的黃色 `color: … !important` 被較後、同 specificity／importance 的綠色覆寫；較後 `.note-pagination { flex-wrap: wrap; }` 與較早同宣告重複，均在全域 scope。
- 精確範圍：只移除舊 `color` 宣告及重複的 `flex-wrap` 規則，**保留原 `font-weight: 700`**。已核對 base 樣式載入、帳號／環境徽章、原生 pager 與其他 CSS 引用；實際 computed style 尚未重驗。
- 收益／最壞影響：去除誤導宣告，效能收益微小；誤刪整條規則可能改變字重或誤傷其他狀態。不涉及資料或外部 API。
- 驗證／回復：前後比較徽章 color／fontWeight、pager flexWrap；雙語、卡片／明細、標準桌面寬度及既有窄視窗退化行為，保留 focus／hidden／disabled／media query。回復僅還原本批 CSS 差異。

### A02：表單初始化前重複 DOM 掃描

**低風險；只簡化初始化，不合併草稿政策。**

- 位置：[project-forms.js:8–9](../app/static/project-forms.js#L8)、[51–68](../app/static/project-forms.js#L51)。
- 證據：`containers` 先掃描一次；同一段同步初始化呼叫 `initialize()` 時，立即以相同查詢覆寫，先前結果沒有被讀取。可用空陣列初始化，保留 `initialize()` 的查詢及局部載入後重新綁定。
- 引用追蹤：取消／Escape／點擊外部、`projmemo:notes-loaded` 與 [project_forms.test.cjs](../tests/js/project_forms.test.cjs)。尚未執行互動驗證；不能把其他看似類似的 dirty 判斷一起改掉。
- 收益／最壞影響：少一次 DOM 遍歷與重複查詢；錯誤調整順序可能破壞取消、密碼清空或焦點返回。不改 API、資料格式或持久化內容。
- 驗證／回復：原 Node 案例加隔離瀏覽器的首次載入、局部換頁重綁、保留／捨棄、Escape 及焦點返回；回復僅還原初始化賦值。

### A03：五個未使用的測試標準函式庫 import

**低風險；不刪除任何測試或斷言。**

- 精確範圍：`test_form_errors.py` 的 [closing／sqlite3](../tests/test_form_errors.py#L1)、`test_web_security.py` 的 [Path／sqlite3](../tests/test_web_security.py#L2)、`test_backup_r11.py` 的 [BytesIO](../tests/test_backup_r11.py#L5)。
- 證據：AST binding 及全文搜尋未見這些匯入名稱被讀取或反射使用；其他測試從 R11 模組匯入的是具名 fixture／helper，不是 `BytesIO`。外部自訂測試消費者未驗證。
- 收益／最壞影響：減少誤導 import；未知消費者若把偶然的 re-export 當 API，可能匯入失敗。影響限測試命名空間，不動 runtime 依賴鎖。
- 驗證／回復：先建立三個模組及使用 R11 helper 的 dashboard／retention 模組基線，移除後重跑並保持所有斷言。回復五個 import 即可。

### A04：現行說明混入歷史功能與測試數量

**低風險；只修現行說明，不改寫歷史紀錄。**

- 位置：[README.md:5](../README.md#L5) 與 [217](../README.md#L217)、[docs/ci.md:26](ci.md#L26)、[browser-regression.md:3](browser-regression.md#L3)／[52](browser-regression.md#L52)；[note-paging.md:36](note-paging.md#L36) 的當時驗收界線可補後續連結。
- 證據：README 開頭稱文件標題仍使用原格式，但同一文件及 [export_options.py](../app/export_options.py) 已提供獨立文件語言；應區分舊一鍵匯出的預設與新選項。CI 現行描述仍列 36／24 項，八份 spec 的來源矩陣已是每引擎 50 例。
- 引用與未驗證：依 [Playwright 設定](../tests/browser/playwright.config.cjs) 及 CI 的 Edge 開關，Windows 150／Linux 100 是來源推算，**不是本輪執行或通過結果**。不應用新數字覆蓋明確日期的歷史 run。
- 收益／最壞影響：減少「功能未完成／數量不符」誤會；最大風險是把推算當成已驗證。建議現行段落描述引擎／矩陣與結果位置，避免再固定容易過時的總數。
- 驗證／回復：核對 renderer 選項與測試宣告，逐段審查只改現況，完整保留 dated counts、原 Roadmap checkbox、失敗與未驗收界線。回復僅撤回該文件批次。

### A05：四份相同 HTML 元素收集 helper

**中風險；可選，不以減少測試數為目標。**

- 位置：[AccountElements](../tests/test_account_ui.py#L11)、[Elements](../tests/test_content_ui.py#L12)、[Controls](../tests/test_desktop_polish.py#L9)、[PageElements](../tests/test_detail_views.py#L7)。
- 證據：忽略類名及參數 annotation 後，四個 class 的 AST 相同：只把 `(tag, dict(attrs))` 依順序放入 `elements`。來源及相關工具／文件只找到各自測試消費者；外部 Python 匯入未驗證。
- 提案：抽一個精確等價的測試 helper；保留全部測試與斷言。會追蹤 form／input 結構的 Backup／Vault parser 不同，不能一起合併。
- 收益／最壞影響：降低四份實作日後分歧；共用 parser 的錯誤也會同時弱化多個 suite，不宜只看刪除行數。
- 驗證／回復：先比對 boolean／duplicate attribute、self-closing tag 與輸出順序，再重跑四個模組。回復四個本地 class，移除新共用 helper；不更新 fixture 或放寬斷言。

### A06：舊前端分頁資源與舊契約測試

**中風險；目前保留，確認退役範圍後再做。**

- 位置：[note-pagination.js:1–45](../app/static/note-pagination.js#L1)、[project_detail.html:184–186](../app/templates/project_detail.html#L184)、[styles.css:361](../app/static/styles.css#L361)、[note_pagination.test.cjs](../tests/js/note_pagination.test.cjs)。
- 直接證據：現行模板載入 `server-note-pagination.js`，未載入舊腳本；舊控制用的 previous／next data attribute 不在現行 markup。`note-page-messages` 的 app 讀者只有舊腳本，`.note-page-paused` 沒有現行 markup 使用。
- 不能直接刪的證據：Node 測試仍讀取舊檔，且測試「全部」與編輯中暫停等舊行為；新伺服器分頁僅有 10／20／50，不能宣稱兩套規格完全等價。Static URL 亦可能被外部直接引用，本輪未盤點外部消費者。
- 精確待審範圍：確認舊功能／static 路徑的退役政策、建立新舊需求對照，再決定舊資源、專用訊息節點／樣式及舊測試的處置；不是先刪檔，再刪失敗測試。
- 必須保留：原生 `_note_pager.html`、目前伺服器分頁、完整匯出、草稿拒絕／明確捨棄、失敗回退、局部重新綁定、共用事件 `projmemo:note-page-change`，以及仍由原生 pager 使用的翻譯 key。
- 收益／最壞影響：消除兩套實作並存的誤導；最壞會破壞外部 static 載入、原生換頁或刪掉仍有產品價值的回歸。未來驗證新分頁 Python／Node、R06 followup 與雙語 JS／原生瀏覽器，回復時整批還原資源與經批准的測試差異。

### A07：本機快取與九個 R11 暫存目錄

**整批以中風險處理；尚未確認可刪，不包含正式資料。**

- 根目錄 `.pytest_cache/` 是可重建的 ignored 快取，單獨處理通常低風險；9 個候選目錄位於 `data/`，名稱及最後修改日落在 2026-10-19。僅查檔案系統中繼資料，沒有開啟其中 DB／備份。
- 精確候選如下，不使用 `data/*` 或遞迴萬用字元取代清單：

```text
data/pytest-r11-final-20261019/
data/pytest-r11-focused-20261019/
data/pytest-r11-full-20261019/
data/pytest-r11-initial-20261019/
data/pytest-r11-language-final-20261019/
data/pytest-r11-release-20261019/
data/pytest-r11-second-20261019/
data/pytest-r11-third-20261019/
data/pytest-r11-ui-probe-20261019/
```

- 引用與缺口：追蹤中的 app／tests／scripts／docs／CI 未查到這九個精確路徑引用；當次程序角色盤點未辨識到 pytest，但不等於證明沒有檔案 handle、外部使用者、環境設定或值得保留的故障證據。目錄年齡與 `.gitignore` 都不是刪除授權。
- 收益／最壞影響：減少本機測試產物雜亂；空間收益未量測，不能承諾釋放多少。誤分類可能失去唯一故障證據或仍被使用的資料。
- 未來驗證／回復：先確認用途、普通目錄／子層 reparse point、解析後的絕對路徑與使用中狀態；由使用者決定是否保留。先移至核准的隔離／封存位置並驗證可回復，再另行批准永久刪除。隔離本身不宣稱釋放磁碟空間；ignored 資料不能靠 Git 還原。
- 明確排除：整個 `data/`、正式 DB／sidecar、`backups/`／`backups/migrations/`、logs、examples、截圖、`.venv`、`data/r06-verify-venv-20261016/`、node_modules、其他未分類測試環境。空 `tools/` 沒有值得優先處理的收益。

### A08：重複的 SQLite authorizer

**高風險；目前建議保留，不排入一般清理批。**

- 位置：[db.py:110](../app/db.py#L110) 的 `_migration_authorizer` 與 [services/vault.py:103](../app/services/vault.py#L103) 的 `_rotation_authorizer`。
- 證據：相同五參數 callback、相同四種拒絕 action（transaction／savepoint／attach／detach）及回傳值；兩者都被 `set_authorizer()` 實際使用，並非死碼。未使用的 callback 參數也不能因靜態警告直接移除。
- 可選提案：未來若確有維護收益，共用政策實作並保留原模組符號；先評估兩個安全邊界是否真的應永遠同政策。外部 Python 匯入未驗證。
- 收益／最壞影響：避免政策分歧；錯誤可能讓 migration 或重加密提早提交，造成難以復原的部分資料變更。少幾行程式不足以合理化此風險。
- 驗證／回復：批准後先建立完整基線，覆蓋 commit／executescript／savepoint／attach／detach 阻擋、兩流程故障回滾、舊備份升級／解密及 session 撤銷。回復程式修補，不刪 migration、不改 schema、不以降版 DB 代替回復。

## 第四階段：分批計畫與批准關卡

以下全部尚未獲得執行批准。批准文件發布不等於批准本表；每批先確認當時 Git／資料狀態及測試基線，完成該批驗證後再處理下一批。

| 狀態／批次 | 對應與精確範圍 | 風險與驗收 | 回復 |
| --- | --- | --- | --- |
| [ ] S01 | R01：三種復原點建立前目錄政策及新增隔離回歸，不放寬下載保護 | 高；先重現，再驗普通目錄及 symlink／Windows junction 下 DB、session、目標不變 | 撤回獨立修補，保留資料及所有快照 |
| [ ] S02 | R02：備份 metadata／預覽清理警告的安全 logger 接線 | 中；故障落檔、敏感值排除、多 app 隔離及 handler 關閉 | 撤回接線，不刪日誌 |
| [ ] B01 | A04：現行 README／CI／瀏覽器總覽及歷史界線交叉連結 | 低；不修改歷史數字、原 checkbox 或把來源推算寫成 pass | 撤回本批文件差異 |
| [ ] B02 | A01：一個失效 color 與一條重複 CSS 宣告 | 低；color／字重／flexWrap、雙語與檢視／鍵盤狀態不變 | 還原兩處宣告 |
| [ ] B03 | A03：三個測試模組內五個標準函式庫 import | 低；原測試及 R11 helper 消費者均通過，斷言不減 | 還原五個 import |
| [ ] B04 | A02：初始化前容器掃描改空陣列，其他邏輯不動 | 低；首次及局部載入、取消／捨棄、密碼清空與焦點正確 | 還原初始賦值 |
| [ ] B05 | A05：四份等價 parser 抽共用測試 helper | 中／可選；輸出等價、四模組及異常 markup 覆蓋不減 | 還原本地 class 與 import |
| [ ] B06 | A06：先完成舊分頁規格／static URL／測試的退役審查，才提交精確刪除清單 | 中／有前置條件；保留當前原生分頁、草稿與完整匯出 | 整批還原舊資源及核准測試差異 |
| [ ] B07 | A07：僅根快取及上述九目錄的用途確認／可回復隔離 | 中；逐一解析路徑、使用中檢查、封存可回復；永久刪除另批批准 | 從核准隔離位置還原，不能靠 Git |
| [ ] B08 | A08：authorizer 共用，僅在另有明確維護需求時考慮 | 高／建議暫緩；完整 migration／密碼更換與故障基線不可省略 | 撤回程式，不回寫舊資料 |

建議先審查 S01 的重現／修正範圍，再視需要安排 S02；純整理可從 B01 → B02 → B03 → B04 開始。B05、B06、B07 需額外確認，B08 現在不建議為縮短程式而執行。

批准後仍應保持每批小而可逆；是否 commit／push 依該次明確授權決定。遇到新風險、既有失敗或範圍變更，停止該批並另報，不自動擴大到下一批。

## 第五階段：唯讀檢查、基線與驗證成本

### 本輪實際完成

| 檢查 | 結果及限制 |
| --- | --- |
| Git／原檔雜湊 | 223 個 tracked 檔與提示共 224 檔，唯讀調查前後 SHA-256 一致；staged／unstaged 程式差異為零 |
| Python 語法 | 107 個 app／scripts／tests Python 檔 AST 解析成功；使用標準函式庫與 `-I -B -S`，不匯入 app 或產生 bytecode |
| JavaScript 語法 | 47 個 JS／CJS 檔 `node --check` 成功；只檢查語法，不執行腳本或測試 |
| JSON 語法與重複 key | 8 個 JSON（catalog、契約、瀏覽器 package／lock、既有依賴審計檔）解析成功，無重複 key；不是 catalog 語意驗證 |
| 文件目標連結 | 稽核前 27 份 Markdown 的本機目標檔案存在；沒有驗證遠端連結或所有 heading anchor |
| 入口補查 | 補查次級 `password_router` 後為 53 組來源宣告；沒有呼叫 app factory 來列出 runtime routes |
| 依賴用途 | runtime 30 個 pin 與 test lock 40 個 pin 的分層用途仍有效；未發現有充分證據可直接移除的依賴 |

未執行 pytest（包括 collection）、Node 測試、Playwright、build、benchmark、setup、pip 安裝／安全掃描或服務啟停，避免產生本輪尚未獲准的應用／測試檔案。先前 Changelog 的成功紀錄不是本次測試結果；2026-10-15 的依賴掃描也不能當作 2026-10-22 的最新漏洞結論。

### 批次獲准後的驗證策略

- B01 先做文件現況與歷史區分、連結／格式檢查，不為純文字修改重跑完整服務套件。
- B02／B04 先跑對應 Node 與 UI Python，再用私有 DB 的雙語 JS／原生瀏覽器確認畫面及草稿，不用正式服務驗證。
- B03 跑 `test_form_errors.py`、`test_web_security.py`、`test_backup_r11.py` 及 backup dashboard／retention 消費者；B05 先跑四個 UI 模組與 parser 等價邊界。
- B06 涉及模板／資源／測試協同退役，須擴至 `test_server_note_paging.py`、`test_r06_followup.py`、Node server-note paging、工作區／表單瀏覽器、完整匯出，不刪失敗斷言或改 fixture 掩蓋問題。
- S01／S02／B08 涉及跨模組及安全邊界：先建立針對性基線及故障重現，再完整 Python／Node／相關瀏覽器回歸，保留既有停止期限、零 retry、HTTP 契約與密碼排除規則。
- 每次使用全新、可核對的私有測試目錄；異常先分析原始原因，不重複跑相同未變測試刷綠，不降低 quality gate。Linux／CJK 手動 gate、真正桌面縮放及 OS 剪貼簿仍需另行明確安排。

原檔程式修補以獨立差異／提交回復，不使用 `reset --hard`／`git clean`；有其他人的修改時先停下，不覆蓋。實際資料與 ignored 暫存的回復須依封存／備份，不依賴 Git。

## 第六階段：本輪交付、保留項目與剩餘風險

### 已批准及實際變更

- 只新增本報告，並將本報告與 `prompts/SAFE_CODEBASE_AUDIT.md` 原檔納入版本控制、提交推送。
- 預期 Git 差異只有兩個新增 Markdown 檔；原 223 個 tracked 檔內容不變，提示原檔雜湊不變。
- 依使用者要求，本次純文件提交加入 `[skip ci]` 略過 GitHub Actions；不修改 workflow，也不手動觸發 CI。
- **實際程式、測試、依賴、設定、資料及清理變更：零。** 沒有刪除、移動快取或測試暫存，也沒有執行本報告中的未來測試。

### 明確保留

- 全部 R05／R06／R08 等階段名稱測試、frozen HTTP 契約、舊 migration／WAL／rollback／並發與敏感資料排除測試。歷史名稱不代表沒有現行回歸價值。
- `load_project_page()` 雖不在現行分頁 UI 路徑，仍由 `benchmark_r03.py`／`benchmark_r05.py` 使用；完整 `ProjectData`、完整／分頁查詢與普通／敏感匯出有不同責任，不是可互刪的重複實作。
- 原一鍵匯出、相容上傳還原、health probe、來源／CSRF／安全錯誤回填、單次送出與 ContextVar／maintenance 保護。
- Windows Selector／重載／console helper、佔用 port 及真正 Ctrl+C 測試。不同入口與故障邊界不能因測試名稱相近合併。
- 全部 requirements 來源、runtime／test 雜湊鎖、維護工具與 CI bootstrap、瀏覽器 npm 鎖；Uvicorn extras 有動態載入用途，不能只靠 import 搜尋刪除。
- 保管庫全域遮蔽／session 同步、原生 Markdown 預覽 sandbox／CSP、兩種不同 dirty 判斷、使用者原文與 UI／匯出／模板三類語言資料邊界。
- `.venv`、驗證環境、正式資料與快照、尚未個別辨識的本機產物；不把整個 ignored 目錄當垃圾。

### 尚未驗證與下一步

本次不是完整滲透測試、惡意備份資源壓力測試、當前 CVE 掃描、Windows 實機／Linux／字型驗收，亦未證明所有外部 API／static 消費者不存在。正式 DB／備份與使用者資料沒有被打開檢查；所有測試函式也不是逐行全覆核。

下一步由使用者依 S01／S02 或 B01–B08 指定批准範圍。未明確批准前，保留所有候選；不能因報告已提交、低風險標籤或後續 CI 自動執行而推定獲准清理。
