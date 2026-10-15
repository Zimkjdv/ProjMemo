# R03 查詢、鎖等待與大量內容評估

量測日期：2026-10-15。基準：`527f785` 的 v2 schema／現行完整內容模板；測試只用自建假資料及暫存 DB，不操作正式資料。R03 的量測、索引／鎖策略與分頁評估已交付；**UI 伺服器端分頁尚未上線**，實作與跨請求草稿保護交由 R05／R10 追蹤。

## 可重跑方式

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/benchmark_r03.py --projects 5000 --rows 10 --repetitions 21 --html-repetitions 2
```

腳本在系統 `TemporaryDirectory` 中建立資料庫，正常結束時連同升級前快照一併清除。它不讀取原 `PROJMEMO_DB_PATH` 的資料；HTML 測試只在腳本自己的程序內將該設定指向臨時 DB。輸出為 JSON 行，可自行保存量測結果；不要指向正式庫、也不將假資料庫加入 Git。

本次環境：Windows、Python 3.12.10、SQLite 3.49.1、原有 DELETE journal mode。不是冷啟動／真實瀏覽器／網路延遲或跨機效能保證；快取、磁碟、資料長度與其他程序負載都會影響數字。每個 SQL 先暖機一次，再量 21 次，記錄中位數；VM 指令以每 100 步的 progress callback 另測，避免 callback 開銷污染時間。每組索引前後的完整結果與順序都以 digest 比對。

## SQL 與索引決策

資料集：5,000 個專案，背景專案每類 10 筆內容；目標專案的備註為 250 筆，位在 ID 範圍中段，避免 `LIMIT` 恰好只掃描最後幾筆的偏差。共 50,240 筆備註，其餘 URL／交接／環境／帳號各 50,000 筆。沒有實際帳密，帳號密文字段為空。

| 實際查詢路徑 | 無索引中位數 ms | 索引後 ms | 約略 VM 步數：前 → 後 |
| --- | ---: | ---: | ---: |
| 目標專案 URL（10 筆） | 4.8265 | 0.0571 | 150,100 → 100 |
| 目標專案備註（完整 250 筆） | 27.2142 | 0.7179 | 152,900 → 3,100 |
| 交接項目（10 筆） | 4.3650 | 0.0626 | 150,200 → 200 |
| 環境說明（10 筆） | 4.6407 | 0.0611 | 150,300 → 200 |
| 帳號 metadata（10 筆） | 6.4316 | 0.0727 | 150,500 → 300 |
| 首頁前 20 筆 | 0.5853 | 0.0837 | 37,600 → 200 |
| 狀態篩選前 20 筆 | 0.4733 | 0.0796 | 26,500 → 300 |
| 備註前 20 筆 SQL 原型 | 13.4065 | 0.0907 | 75,200 → 300 |

據此在 **schema v3** 新增七個非唯一複合索引；由正式 migration 建立，沒有 `IF NOT EXISTS` 掩蓋同名錯誤定義：

| 索引 | 欄位與排序 |
| --- | --- |
| `idx_projects_updated` | `updated_at DESC, id DESC` |
| `idx_projects_status_updated` | `status, updated_at DESC, id DESC` |
| `idx_urls_project_order` | `project_id, id DESC` |
| `idx_notes_project_order` | `project_id, id DESC` |
| `idx_checklist_project_order` | `project_id, completed, id DESC` |
| `idx_environment_project_order` | `project_id, CASE environment` 的既有環境順序、`key COLLATE NOCASE` |
| `idx_accounts_project_order` | `project_id, CASE environment` 的既有環境順序、`label COLLATE NOCASE` |

`EXPLAIN QUERY PLAN` 顯示五類內容由全表掃描改為 project 索引查找；交接／環境／一般帳號查詢不再另外排序。CASE 與 collation 須吻合現有 SQL，沒有改變排序規則。參考 [SQLite expression indexes](https://www.sqlite.org/expridx.html)。Plan 僅作診斷，不在產品程式解析其輸出，因其格式可能隨版本改變。[SQLite EXPLAIN QUERY PLAN](https://www.sqlite.org/eqp.html)

敏感帳號匯出另按 label 排序：索引先縮小至該專案，仍有臨時排序；本例 8.7415 → 0.0565 ms。因只剩 10 筆排序，本輪不再建立一份重複的 label 專用索引。`LIKE '%文字%'` 仍可能掃描；本次廣泛匹配的搜尋可因排序索引提早取得 20 筆，**不代表一般子字串搜尋已變成索引查找**。FTS／內容搜尋仍由 R10 規劃。

代價：DB 由 47,443,968 增至 52,363,264 bytes，約 +10.4%。七個索引單獨建立合計約 216 ms，但實際 v2→v3 runner **約 3,593 ms**，還包含升級前快照與前後完整驗證；快照為原始 47,443,968 bytes。這不是每次啟動都重建索引，已完成版本不重跑。索引需要磁碟空間與寫入維護成本，不能把 SQL 改善比例當成整頁加速比例。

升級規則、失敗回復及舊版相容性見 [資料庫升級與復原](database-migrations.md)。v3 缺少索引或同名定義不符會拒絕啟動／還原；v0／v1／v2 保留原驗證能力，通過後才逐版升級。未知同名索引衝突時保留原檔與快照、停止升級，不盲目刪除使用者索引。

## 鎖等待策略

先前 sqlite3 預設等待 5 秒，外部 writer 持有 350 ms 的探測中，另一個寫入約在 448 ms 後成功，證實短暫競爭應允許有限等待，而不是立即失敗或無限制重試。

現行規則集中於 `app/sqlite_policy.py`：

- SQLite connection lock wait 明確為 **1 秒**，維持 DELETE journal，不自動切 WAL 或更換 DB。
- 修改服務明確使用 `db_session(write=True)`，以 `BEGIN IMMEDIATE` 在執行業務邏輯前預留 writer；普通讀取使用 `BEGIN`，同一次多表查詢保有一致快照。這不是多程序支援。
- BUSY／LOCKED（含 extended code）回滾後轉為雙語 503、`Retry-After: 1`、禁止快取；不回傳 SQL 或資料內容。不自動重播業務交易，使用者明確重試；非鎖定 SQL 錯誤不偽裝成「忙碌」。
- SQLite backup API 有自己的重試機制，因此另以 progress callback 限制連續 BUSY／LOCKED 等待約 1 秒；健康的大檔案複製沒有一秒總執行期限。連線、callback 排程及作業系統負載仍會影響實際回覆時間，這不是嚴格即時 deadline。
- commit 因 reader 不能完成時回滾此次交易，不留下半筆內容或專案時間；若 rollback 本身失敗，阻止一般存取並要求停止程式後檢查／復原。
- 原有還原排他權仍等已接納作業最多 10 秒，期間拒絕新作業；它不同於 SQLite lock timeout。升級／還原的回復仍保有獨立復原點。

busy timeout 的作用是有限等待鎖，不是重新執行整段業務程式。[SQLite busy_timeout](https://www.sqlite.org/pragma.html#pragma_busy_timeout) 請勿把延長 timeout 當成可以開多 worker 的依據。

## HTML／模板與 UI 分頁評估

另用只有一個專案的 UI fixture，固定各 20 筆 URL／交接／環境／帳號，僅改變備註數。備註含相同長度的中英文 Markdown。各量測暖機後取兩次中位數；DB、直接 template render、完整 TestClient request 分開量，**不能將三欄相加**，request 已包含自己的 DB／render。

| 備註數 | 完整 HTML bytes | DB ms | 直接模板 ms | 完整 request ms |
| ---: | ---: | ---: | ---: | ---: |
| 20 | 405,165 | 1.79 | 25.95 | 30.71 |
| 250 | 1,432,432 | 3.15 | 196.30 | 199.74 |
| 1,000 | 4,780,726 | 7.50 | 845.81 | 931.37 |

判斷：索引解決跨專案掃描；不能消除完整載入本文、Markdown 清理、每筆編輯表單、HTML 傳輸與 DOM 的線性成本。20 筆樣本顯示限量渲染有價值，但它不是已完成的伺服器端分頁，也未模擬完整的分頁控制／草稿保護或瀏覽器 layout 時間。現有前端分頁仍只隱藏 DOM，本輪不更動 UI 或宣稱已把 1.4 MB 的頁面縮小。

### 已定案的後續設計（待 R05／R10 實作）

1. **只分頁 UI 備註**，先支援 10／20／50；其他內容量測後再決定。頁面要有獨立的總筆數／目前頁資訊，不能把目前頁長度誤作總數或取消雙重計數。真正「全部」另設明確重載入口與大頁面提示，不作預設。
2. 保留完整 `ProjectData`／`load_project_data()` 給 Markdown、PDF 與敏感匯出；新增 UI 專用 view model／查詢，而不是在既有完整投影上默默加 LIMIT。備份仍保留全庫。
3. 先以 `project_id + id DESC` 的索引和 `COUNT／LIMIT／OFFSET` 支援個人版頁碼；資料變動時顯示重新整理，不宣稱 OFFSET 在跨分頁新增／刪除下不會重排。深頁成本另量測，有需求才改 cursor，不把首頁分頁或匯出一起改寫。
4. 以相同安全 context 產生 HTML 局部內容，漸進增強只更換備註清單；保留原生完整 URL 回退。卡片／明細與總數保留，不將帳號密碼納入新回應、URL 或 storage。此文件沒有宣告已存在的新 API。
5. **草稿先行**：有變更的備註編輯不直接換頁，先完成取消／明確捨棄或阻止切換；其他分類及新增表單的 DOM 保留。原生跳頁、切語言及離開頁面需 R05 全頁提示，不能只保護備註。密碼只留目前記憶體／DOM、不得持久化、回填或夾入局部載入；到期遮蔽及延遲 reveal 防護維持。
6. 網路失敗不得先清除現有清單或草稿；保留目前頁與可重試狀態、防重複點擊，變更或離開提示都要中英文可用。每次換頁只初始化新節點，不累積重複事件監聽或計時器。
7. 驗收須包含兩語、兩模式、空／250／1,000 筆、長文、深頁、未存草稿／拒絕捨棄、錯誤回退、保管庫到期及鍵盤操作；普通／敏感 Markdown／PDF 內容仍完整，並量測真實瀏覽器 DOM／layout，而不只看 SQL 或隱藏列數。

### 本輪完成範圍

R03 原始兩條剩餘待辦分別要求「量測後補索引與鎖策略」及「評估 UI 分頁與草稿／匯出邊界」；以上已完成並移至 Changelog。實際 UI 分頁是有相依條件的新交付項目，已明列 [ROADMAP.MD](../ROADMAP.MD) 的 R05／R10，未把未實作的功能勾選完成。

測試使用 VM 工作量／查詢結果及真實鎖衝突，不以毫秒倍數當 CI 門檻。schema v0／v1／v2 升級、部分索引失敗回復、重啟冪等、錯誤索引拒絕、原密碼解密、交易／commit 回滾與既有安全功能一併回歸。實機縮放、R08 的完整 PDF 視覺與系統剪貼簿驗收仍不在這次完成範圍。
