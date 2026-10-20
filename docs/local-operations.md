# 本機安裝、啟動與維運

## 安裝與日常執行

Windows 使用 `setup-local.bat` 建立／檢查 `.venv` 並安裝專案依賴；只在首次安裝或明確更新時執行。venv 建立失敗回傳 1、pip 不可用回傳 2、安裝或匯入檢查失敗回傳 3，不輸出「安裝成功」或繼續啟動。

日常 `run-local.bat` 使用 `.venv\Scripts\python.exe` 的明確路徑，不依賴 activate 或目前 shell 的 Python，也不執行 pip／套件安裝。缺環境或依賴時顯示需先執行 setup 的指引，非零結束。`run-local.bat --check` 只檢查匯入，不開啟資料庫；已裝妥的環境可離線使用。

兩個 batch 均先切換到腳本目錄，路徑有空白也可使用；可從任意本機工作目錄以腳本完整路徑呼叫。其他手動指令須自行切換至專案根目錄。不要在不明 venv／套件錯誤後刪除資料庫；修復環境與資料復原是不同操作。

## 一般與開發模式、port

`run-local.bat` 預設一般模式，不重載；`run-dev.bat` 或 `run-local.bat --dev` 才啟用開發重載。固定 IPv4 loopback `127.0.0.1` 與單 worker，不接受 `--host`／`--workers`。開發模式另有監督程序，但只有一個應用 worker；重載會撤銷記憶體中的解鎖與舊表單 token，須重新整理頁面。

Windows 正式入口使用 Selector 相容性策略，避免 Python 3.12.10 Proactor 在連線重設後停止接收／清理；開發重載以私有 Event 等待舊 worker 正常退出，不廣播 Ctrl+C。僅採用存在的監看排除目錄，程式副本不必含 `.git`／`tests`。不改 Linux、依賴或資料庫，限制與可重跑的 OS Ctrl+C／真實重載驗證見 [Windows 啟停驗證](windows-lifecycle.md)。這些變更需重新啟動正式服務才會完整套用，不對現有服務熱更新 venv。

預設從 8000 至 8099；`PROJMEMO_PORT` 或優先的 `--port` 可改起點（1–65535）。最多嘗試 100 個 port，上限截在 65535；`--port-end` 可縮小範圍。例：`run-local.bat --port 8123 --port-end 8130`。不是 TCP 探測後重新綁定：launcher 直接 bind/listen 並持有同一 socket，交由 Uvicorn（包含 Windows reload child）使用；被占用／系統保留的 port 才往下試，其餘網路錯誤立即失敗。不終止其他使用者的服務。

環境或參數錯誤／無可用 port 回傳非零（通常 2，缺 venv 為 1），一般模式啟動失敗回傳 3。終端機網址表示 socket 已保留，需等待 application startup complete 才代表已就緒。開發監督程序在子程序啟動錯誤後可能仍存活、等待修正，不能只憑監督程序存活判斷成功。Ctrl+C 停止服務。`--check` 不 bind、不開 DB、不安裝套件。

## 依賴維護

目前支援 Windows x64／CPython 3.12。setup 只安裝根目錄 `requirements.txt` 的含雜湊 runtime 鎖，測試需另外明確安裝 `requirements/requirements-test.txt`；其餘人工需求及維護工具清單也集中在 `requirements/`。版本閉包、更新／離線安裝與 2026-10-15 實際安全掃描見 [依賴維護](dependencies.md)。勿對正在執行的服務熱更新 venv；先停止、備份，再 setup。

## 健康與故障處理

`/health/live` 是程序存活，`/health/ready` 才確認啟動／DB 可讀及操作准入；不回傳敏感資料或自動重建 DB。啟動前檢查父目錄可寫與 64 MiB 基本剩餘空間，失敗以固定分類停止。安全日誌在 DB 同目錄 `logs/`，約 1 MiB × 4 輪替，不包含請求欄位與例外內容；完整分類、故障處理與檢查限制見 [健康與日誌](operations-health.md)。

## R07 驗收基線（2026-10-15）

| 情境 | 明確結果與證據 |
| --- | --- |
| 其他工作目錄 | 從含空白的另一個 cwd 呼叫完整路徑 `run-local.bat`／`run-dev.bat`，真實 HTTP 與 ready 成功；setup／check 也有 batch 回歸。 |
| 已安裝、離線使用 | `PIP_NO_INDEX=1` 下啟動／check 不安裝、不升級、不呼叫 pip；純 runtime 新 venv 無 pytest／httpx 仍通過 check。首次安裝／更新另需網路或預備 wheelhouse。 |
| 第一個 port 占用 | 持有占用 socket，module 與 batch 的 normal／reload 四種組合均換 port 並完成 HTTP／ready；嘗試有界，單一占用範圍拒絕，未終止既有服務。 |
| 安裝失敗 | 真正隔離 venv 測試 pip 缺失、禁止網路時無法取得套件；venv 建立失敗也有 batch 路徑回歸。非零結束、無成功訊息、不啟動、不開正式 DB。 |
| 啟動／儲存失敗 | 真實子程序在壞 DB 退出 3 且保留原檔；低空間、錯路徑、不可寫與 log 故障固定分類。日誌／HTTP 不含敏感 sentinel。 |

測試檔為 `tests/test_local_setup.py`、`tests/test_launcher.py`、`tests/test_dependencies.py`、`tests/test_operations.py`。只在隔離 DB／venv 驗證，維護工具、生成中間檔與 pytest 暫存不隨 Git 發布。既有正式 venv 未熱更新，因此測試不冒充目前舊服務已載入新依賴；請依上述 stop → setup → run 流程套用。
