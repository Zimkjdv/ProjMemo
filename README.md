# ProjMemo

ProjMemo 是一個以本機 Python `.venv` 執行的個人專案備註與交接清單管理工具，用來集中保存專案 URL、注意事項、已知問題、環境設定說明與交接資訊；Docker 化安排在功能接近完成後。

## GitHub Repository 建議

- **Repository name**：`projmemo`
- **Description**：`A personal project knowledge base and handover checklist manager with Markdown and PDF export.`
- **中文描述**：個人專案備註與交接清單管理工具，支援重要 URL、Markdown 備註、環境設定說明及 Markdown/PDF 匯出。

## 主要目標

- 集中管理個人或團隊專案資訊
- 快速記錄重要 URL 與專案注意事項
- 保存 Known Issues 與 Workarounds
- 將專案內容整理成交接清單
- 一鍵匯出 Markdown 或 PDF，方便交接與寄送
- 下載 SQLite 備份，並在還原前自動保留目前資料

## 預計功能

目前已提供 URL、Markdown 備註、交接清單、環境變數說明，以及 Markdown/PDF 匯出。

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
- 規劃支援 Mermaid，方便記錄架構圖與流程圖

### 3. Handover Checklist

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
- 不接受不相容或損毀的備份；驗證失敗時不會更動目前資料
- 每次還原前會自動保留一份可下載的還原前備份
- 還原上傳限制為 100 MB
- 還原前備份保存在目前資料庫所在目錄的 `backups/` 子目錄，最多顯示最近 10 份且不會自動刪除

## 初步資料模型

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

環境變數區只記錄設定用途、套用環境及 Secret 的存放位置或負責人，不提供 Secret 值欄位。重要 URL 與環境變數也可編輯或刪除。

## 技術方向

- Backend：FastAPI
- Initial UI：Jinja2 + HTML/CSS
- Database：SQLite
- Local runtime：Python `.venv`
- Later deployment：Docker Compose
- 文件格式：Markdown
- PDF：ReportLab 產生 A4 文件

PDF 匯出會包含專案資料、重要 URL、備註中的 Markdown 內容、環境變數說明及交接清單，並加入頁首、頁尾與頁碼。繁體中文字型會自動尋找作業系統字型（Windows 優先使用 Microsoft JhengHei；Linux 可安裝 Noto Sans CJK）。如需指定字型，可設定 `PROJMEMO_PDF_FONT`；粗體字型可選用 `PROJMEMO_PDF_BOLD_FONT`。

目前先以本機 `.venv` 執行，確認資料模型與使用流程接近完成後，再進行 Docker 化。第一版不急著導入 MySQL、複雜權限或多使用者架構。未來若需要多人協作，再考慮切換至 PostgreSQL 或 MySQL。

## 本機開發

Windows 可執行：

```bat
run-local.bat
```

或手動執行：

```powershell
py -3 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

啟動時會從 `8000` 開始自動尋找可用 port；如果 `8000` 被其他程式使用，會依序改用 `8001`、`8002` 等。終端機會顯示實際網址。本機 SQLite 資料會建立在 `data/projmemo.db`，此資料目錄已加入 `.gitignore`。

若要手動指定 port：

```powershell
$env:PROJMEMO_PORT = "8123"
python -m uvicorn app.main:app --reload --port $env:PROJMEMO_PORT
```

## 安全原則

ProjMemo 不應直接保存密碼、API Key 或其他 Secret。建議只記錄：

- Secret 的存放位置
- 申請或取得方式
- 負責人
- 使用環境
- 相關文件連結

## 開發階段

### Phase 1：基本專案管理

- [x] 專案 CRUD
- [x] Project Basic Info
- [x] 重要 URL（含編輯與刪除）
- [x] Markdown 備註（含編輯與刪除）

### Phase 2：交接資訊

- [x] Handover Checklist（含編輯、刪除與完成狀態）
- [x] 環境變數說明
- [x] Known Issues 與 Workarounds

### Phase 3：匯出與搜尋

- [x] Markdown 匯出（包含環境變數說明）
- [x] PDF 匯出（包含繁體中文字型、表格與頁碼）
- [x] 專案搜尋
- [x] 標籤與狀態篩選

### Phase 4：延伸功能

- [x] SQLite 備份與還原（含驗證及還原前自動備份）
- 登入與權限
- 多使用者
- Git 同步或版本紀錄

## 後續 Docker 化方向

預計以 Docker Compose 啟動應用程式，並將 SQLite 資料庫掛載至 named volume 或指定資料目錄，確保容器重建後資料仍然保留。

開發環境應保留 hot reload，讓程式修改不需要每次重新建立 Docker image。
