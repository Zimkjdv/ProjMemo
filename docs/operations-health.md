# 本機健康檢查與安全日誌

## 健康檢查

使用啟動時顯示的實際 port，預設 8000，若衝突可能為 8001 等：

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health/live
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

`/health/live` 只回覆 `{"status":"alive"}`（200），不碰資料庫。`/health/ready` 在啟動成功且 DB 可讀、版本符合、未還原／未要求復原、剩餘空間至少 64 MiB 時回覆 `{"status":"ready"}`（200），否則只有 `{"status":"not_ready"}`（503）。不公開路徑、schema 版本、磁碟容量、專案數量或保管庫狀態。兩者皆 no-store，沿用本機 Host／來源限制，不加入業務 OpenAPI 文件。

readiness 以 `mode=ro` 開啟 SQLite，最長等待鎖 0.2 秒，不建立遺失的 DB、不升級、不寫入或讀取帳密值。它是便宜的可讀／啟動與操作准入檢查，不代替完整 integrity／備份復原驗證，也不保證每次寫入或大型匯出都成功。還原與手動復原阻擋期間 live 仍為 200，ready 為 503；不能把 supervisor／PID／live 存活誤認為資料服務正常。

## 錯誤日誌

目前 DB 所在目錄的 `logs/projmemo.log` 保存 startup／shutdown 與 5xx 錯誤摘要；例如預設為 `data/logs/projmemo.log`。單份約 1 MiB，保留目前檔案加 3 份輪替（總量約 4 MiB，單筆邊界可能略超），不刪除任何 DB／備份。每個 app 在結束時關閉自有 handler，避免 Windows 鎖住檔案。日誌同時顯示在終端機；不要把它誤認為完整操作稽核。

每個 HTTP 回應有伺服器新建的 `X-Request-ID`；非預期錯誤回應另有相同的 `request_id`。查核可憑此值找到 `request_failed`，只記 method 白名單、程式定義的 route 模板（如 `/projects/{project_id}/accounts`）、HTTP status 與固定錯誤分類。未匹配路由只記 `unmatched`。不採用客戶端送來的追蹤 ID，也不記 raw URL／query／動態路徑值、表單／JSON、帳號密碼、cookie、Authorization、例外文字或 traceback。正常使用 launcher 會停用 Uvicorn raw access log；不要改以自訂 `--log-level debug`／外部 access logger 來擴大紀錄範圍。

非預期 SQLite／儲存 I/O 失敗回覆安全的 503，其餘未預期錯誤為 500，繁中／英文均不回顯原始內容。既有可恢復表單與還原錯誤流程保持不變。若串流已開始後才失敗，不會再送第二個錯誤回應，而以安全例外讓服務關閉失敗的串流；不得把已開始的 200 當成匯出成功，仍需確認下載完整性。啟動失敗僅輸出分類與維運指引，migration 例外仍保留 snapshot 屬性供程式內復原，但不在 HTTP／錯誤文字中攤開 DB 與例外內容。

`LOG_WRITE_FAILED` 表示執行中日誌無法寫入／輪替，使用固定終端提示、不退回列出敏感例外。它不保證磁碟故障時仍能留下檔案紀錄，需檢查終端與磁碟。啟動時不能建立日誌目錄會停止啟動，不能悄悄宣告服務就緒。Uvicorn 的啟動失敗輸出可能仍顯示呼叫堆疊，但只帶已淨化的例外，不帶原始 exception chain；原始 DB 錯誤內容不會因此攤開。背景 session 清理失敗亦只記固定分類，稍後再清理，不列印例外文字。

## 資料目錄與空間問題

啟動前確認資料路徑不是目錄、既有 DB 可讀寫、父目錄可建立／寫入／fsync／刪除一個私人 probe，且至少 64 MiB 可用。probe 只含固定非敏感文字並會移除，不修改既有 DB。仍須確保 DB 目錄、`logs/`、`backups/`、`backups/migrations/` 及系統暫存目錄有足夠權限與空間；啟動 probe 不能保證稍後 ACL／磁碟狀態不會改變。

| 分類 | 處理方式 |
| --- | --- |
| `DATA_PATH_INVALID` | `PROJMEMO_DB_PATH` 必須是檔案路徑，不是資料夾。停止程式後更正設定，不刪除原資料。 |
| `DATA_DIRECTORY_UNWRITABLE`／`STORAGE_ERROR` | 檢查目前帳號對 DB、父目錄與 logs 的權限、唯讀屬性、防毒／同步工具鎖定、系統 temp。不要用系統管理員權限掩蓋未知問題。 |
| `DATA_SPACE_LOW`／`DATABASE_ERROR` | 檢查磁碟與 SQLite 狀態，釋出確定不需保留的其他檔案；保留 DB 與備份。寫入失敗已回滾的作業可在確認後重試，先檢查是否已成功。 |
| `DATABASE_INIT_FAILED` | schema／migration 初始化未完成，服務不接受資料請求；保留 DB 與升級前快照，依升級復原指南處理。 |
| `DATABASE_RECOVERY_REQUIRED` | 自動復原未成功，停止服務並依指南從快照復原，不能刪 DB 後重新啟動當作修復。 |

64 MiB 是基本下限，不是大型備份／還原的容量保證：升級快照另需目前 DB 大小；還原還需上傳檔、還原前備份、替換與復原空間，系統 temp 可能在另一個磁碟。操作前額外預留這些容量。程式不會自動刪除備份、資料庫或任意 pytest 目錄來換取空間。

更多步驟見 [備份復原](backup-recovery.md)、[migration 復原](database-migrations.md) 與 [本機啟動](local-operations.md)。停用網路公開與妥善保護 OS 帳號仍是個人版的安全前提；安全日誌不會將未加密的一般專案資料變成加密資料。
