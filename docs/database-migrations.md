# SQLite 結構升級與復原

ProjMemo 仍使用本機 SQLite 與單程序、單 worker。啟動時由 `app/db.py:init_db()` 執行版本化遷移；不需另外安裝 Alembic，也不會將資料上傳到遠端。

## 版本與紀錄

| 版本 | 結構與處理方式 |
| --- | --- |
| 0 | 未標記版本的舊資料庫。只接受完整的五張核心表，或再加完整三張保管庫表；先驗證，不以建立缺少的表掩蓋毀損。全新空資料庫也是從 0 開始。 |
| 1 | 先前已發布的八張業務表。0 → 1 建立新資料庫，或為五表舊版加入保管庫三表；既有資料與 ID 不變。 |
| 2 | 新增 `schema_migrations` 紀錄表。版本 1 本來沒有遷移紀錄，因此不補造它的執行時間，紀錄自 2 起。 |
| 3 | 依量測新增七個專案查詢／排序索引，不改業務欄位或密文。v3 同時驗證必要索引定義。 |
| 4 | 現行版本；新增 `archived_at`、`deleted_at`、`revision` 與生命週期索引。既有專案預設使用中、revision 0，原 ID／欄位值／密文不改；驗證時間、非負 revision 與索引。 |

`PRAGMA user_version` 是已提交的 schema 版本。`schema_migrations` 保存 `version`、固定的 `name` 及 UTC `applied_at`；兩者必須一致。未知的較新版、結構不完整、關聯錯誤或紀錄不符都拒絕啟動／還原，不降版、不自行重建資料表。

一般修改專案內容不改 schema 版本。v4 只追加生命週期欄位；既有欄位值、ID、時間、保管庫 salt、KDF 參數、密文、nonce 及加密 AAD 都不重寫，仍以原主密碼解鎖。不得手動降低版本號或去掉紀錄繞過檢查；低於 v4 卻含生命週期欄位的檔案會被拒絕。操作見 [專案生命週期](project-lifecycle.md)。

## 啟動升級流程

1. 檢查 `app/migrations.py` 的登錄是否由 1 到最新版本連續排列，不接受缺版、重複或亂序。
2. 取得程序內排他維護權，等既有作業完成，新的資料操作暫時拒絕。以 `BEGIN IMMEDIATE` 保留 SQLite 寫入權；其他 SQLite 寫入者尚未釋放鎖時，依明確的一秒 lock timeout 停止，不強制解鎖。健康的升級／快照沒有一秒總執行期限。
3. 驗證現有結構、完整性、關聯、保管庫格式及版本。已是最新版時只驗證，**不重跑 migration、不更動執行時間、不新增快照**。
4. 既有舊版資料庫升級前，以另一個唯讀連線及 SQLite backup API 建立並驗證快照。它包含已提交的 WAL 資料，不直接複製可能不完整的 `.db` 主檔。快照失敗即停止，尚未執行任何 schema 修改。全新空庫沒有舊資料，不建立空白快照。
5. 在**同一筆交易**依序執行缺少的版本，逐版更新 `user_version`，自版本 2 起登錄紀錄；通過最後完整性／結構檢查才一併提交。任何一步失敗都不保留前面幾版的半套成果。
6. 初始化失敗不啟動 Web 服務。若是還原舊備份，遷移共用還原流程已持有的排他權，仍不允許第二次還原或一般請求插入。

交易中使用逐條 `execute()`，不使用會隱式提交的 `executescript()`。遷移回呼執行期間也拒絕交易／savepoint／附加資料庫指令，降低誤提交的風險；回呼仍是可信任的程式碼，不是執行不可信程式的沙箱。參考 [Python SQLite 交易說明](https://docs.python.org/3.12/library/sqlite3.html#transaction-control-via-the-isolation-level-attribute)、[SQLite transaction](https://www.sqlite.org/lang_transaction.html)、[SQLite backup API](https://www.sqlite.org/backup.html)。

## 升級前快照

預設資料庫的快照位置：

```text
data/backups/migrations/
  projmemo-pre-migration-v3-to-v4-<UTC時間>-<隨機字串>.sqlite3
```

若有設定 `PROJMEMO_DB_PATH`，位置為該資料庫所在目錄的 `backups/migrations/`。日誌及升級失敗例外會提供路徑，不記錄帳號密碼或資料內容。一次跨多版升級保存一份升級前快照；失敗後重試會另存，不覆蓋前次復原點。

快照不會自動刪除，目前不列在備份頁「自動復原點」的最近 10 份清單；它與 `backups/projmemo-pre-restore-*.sqlite3` 及 `projmemo-pre-delete-*.sqlite3` 不同。可從檔案系統另外保存或在備份頁選檔還原已支援的舊版本，但新版程式會再次升級該檔案的還原結果。

實際密碼為密文，其他專案／帳號欄位仍為明文；快照不含主密碼或解密金鑰，但仍須按敏感備份保護。請另外保存獨立備份，不要只依賴同磁碟的自動快照。

## 失敗與人工復原

- **驗證或快照失敗**：不執行遷移；修正版本、來源、磁碟空間或權限問題後再試。不要手改 `user_version` 或刪除紀錄來繞過檢查。
- **遷移／最終檢查／提交失敗**：回滾並關閉連線，再由升級前快照回復、驗證原版本。即使回復成功，本次啟動仍失敗；修正程式或環境後才重新啟動。
- **自動回復也失敗**：保留錯誤中的快照路徑，程序內標記需要復原並阻止一般資料存取。重啟會清除程序內標記，因此不能只重啟就假定資料已修復。完全停止所有 ProjMemo 程序及其他 SQLite 工具，依 [備份復原指南](backup-recovery.md#自動回復失敗的人工處理) 保留現有 DB／sidecar，在另一個空目錄用快照復原驗證；本情境啟動未完成，不能依賴 Web 下載頁。
- 需要暫回舊版程式時，使用相符版本的**升級前快照副本**及原主密碼驗證，不能讓只支援 v3 的舊程式直接操作 v4 資料庫。保留原資料與所有復原點，不覆寫唯一副本。

本流程涵蓋正常執行時的交易、快照與錯誤復原，不保證硬體故障、斷電或程序強制終止的全部災難復原情況。程序內維護權不能協調外部工具或多個應用程序；仍禁止多 worker／同時啟動兩個 ProjMemo 共用資料庫。v3 只新增量測過的索引，不切換 WAL 或改動保管庫加密格式；同名索引衝突不盲目刪除／覆寫。量測及鎖策略見 [R03 效能評估](performance-r03.md)。

## 新增下一版 migration

1. 在 `app/migrations.py` **追加**版本 5 與固定名稱的回呼，並提高 `SCHEMA_VERSION`；不可修改、刪除或重新排序已發布的遷移。版本 1 是歷史基準，版本 2 是紀錄起點，版本 3 是查詢索引，版本 4 是專案生命週期。
2. 回呼只操作傳入連線，不自行 commit／rollback／executescript／savepoint／attach，也不開另一條寫入連線、不呼叫網路或修改 DB 以外的檔案。整批交易與失敗復原由 runner 管理。
3. 更新 `app/schema_validation.py`，保留每個支援舊版的驗證能力，讓啟動前與還原前能辨識真正舊結構；不以當前欄位要求拒絕有效舊備份。
4. 增加隔離的舊版升級、跨多版中途失敗、快照失敗、密文解密、還原及重啟測試；測試只用暫存 DB，**不要指向 `data/projmemo.db`**。

本輪測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/js/*.test.cjs
```
