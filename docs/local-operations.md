# 本機安裝、啟動與維運

## 安裝與日常執行

Windows 使用 `setup-local.bat` 建立／檢查 `.venv` 並安裝專案依賴；只在首次安裝或明確更新時執行。venv 建立失敗回傳 1、pip 不可用回傳 2、安裝或匯入檢查失敗回傳 3，不輸出「安裝成功」或繼續啟動。

日常 `run-local.bat` 使用 `.venv\Scripts\python.exe` 的明確路徑，不依賴 activate 或目前 shell 的 Python，也不執行 pip／套件安裝。缺環境或依賴時顯示需先執行 setup 的指引，非零結束。`run-local.bat --check` 只檢查匯入，不開啟資料庫；已裝妥的環境可離線使用。

兩個 batch 均先切換到腳本目錄，路徑有空白也可使用；可從任意本機工作目錄以腳本完整路徑呼叫。其他手動指令須自行切換至專案根目錄。不要在不明 venv／套件錯誤後刪除資料庫；修復環境與資料復原是不同操作。

## 一般與開發模式、port

`run-local.bat` 預設一般模式，不重載；`run-dev.bat` 或 `run-local.bat --dev` 才啟用開發重載。固定 IPv4 loopback `127.0.0.1` 與單 worker，不接受 `--host`／`--workers`。開發模式另有監督程序，但只有一個應用 worker；重載會撤銷記憶體中的解鎖與舊表單 token，須重新整理頁面。

預設從 8000 至 8099；`PROJMEMO_PORT` 或優先的 `--port` 可改起點（1–65535）。最多嘗試 100 個 port，上限截在 65535；`--port-end` 可縮小範圍。例：`run-local.bat --port 8123 --port-end 8130`。不是 TCP 探測後重新綁定：launcher 直接 bind/listen 並持有同一 socket，交由 Uvicorn（包含 Windows reload child）使用；被占用／系統保留的 port 才往下試，其餘網路錯誤立即失敗。不終止其他使用者的服務。

環境或參數錯誤／無可用 port 回傳非零（通常 2，缺 venv 為 1），一般模式啟動失敗回傳 3。終端機網址表示 socket 已保留，需等待 application startup complete 才代表已就緒。開發監督程序在子程序啟動錯誤後可能仍存活、等待修正，不能只憑監督程序存活判斷成功。Ctrl+C 停止服務。`--check` 不 bind、不開 DB、不安裝套件。

依賴鎖定／安全檢查及維運日誌／健康檢查仍依 R07 後續條目逐項交付。
