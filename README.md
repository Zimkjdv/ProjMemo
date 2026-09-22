# ProjMemo

ProjMemo 是一個 Docker 化的個人專案備註與交接清單管理工具，用來集中保存專案 URL、注意事項、已知問題、部署流程與交接資訊。

## GitHub Repository 建議

- **Repository name**：`projmemo`
- **Description**：`A Dockerized personal project knowledge base and handover checklist manager.`
- **中文描述**：Docker 化的個人專案備註與交接清單管理工具，支援 Markdown、重要 URL 與 Markdown/PDF 匯出。

## 主要目標

- 集中管理個人或團隊專案資訊
- 快速記錄重要 URL 與專案注意事項
- 保存 Known Issues 與 Workarounds
- 將專案內容整理成交接清單
- 一鍵匯出 Markdown 或 PDF，方便交接與寄送

## 預計功能

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

### 2. Notes & Cautions

- 支援 Markdown 格式
- 支援程式碼區塊與表格
- 可記錄一般備註、注意事項、Known Issues 與 Workarounds
- 可設定備註優先等級
- 規劃支援 Mermaid，方便記錄架構圖與流程圖

### 3. Handover Checklist

- 帳號與權限清單
- AWS 或其他雲端權限說明
- 第三方服務與負責人
- 部署步驟
- 環境變數對照表
- 交接項目完成狀態
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

## 技術方向

- Backend：FastAPI
- Initial UI：Jinja2 + HTML/CSS
- Database：SQLite
- Local runtime：Python `.venv`
- Later deployment：Docker Compose
- 文件格式：Markdown
- PDF：由 Markdown 或 HTML 轉換產生

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

- 專案 CRUD
- Project Basic Info
- 重要 URL
- Markdown 備註

### Phase 2：交接資訊

- Handover Checklist
- 完成狀態
- 環境變數說明
- Known Issues 與 Workarounds

### Phase 3：匯出與搜尋

- Markdown 匯出
- PDF 匯出
- 專案搜尋
- 標籤與狀態篩選

### Phase 4：延伸功能

- 備份與還原
- 登入與權限
- 多使用者
- Git 同步或版本紀錄

## 後續 Docker 化方向

預計以 Docker Compose 啟動應用程式，並將 SQLite 資料庫掛載至 named volume 或指定資料目錄，確保容器重建後資料仍然保留。

開發環境應保留 hot reload，讓程式修改不需要每次重新建立 Docker image。
