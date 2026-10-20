# Windows 正式啟動、重載與停止驗證

適用目前 Windows x64／Python 3.12.10、鎖定的 Uvicorn 0.34.2、本機單 worker 個人版。這是正式 launcher 的驗證，不拿 R10 瀏覽器 fixture 的 Selector 結果代替正式入口，也不變更 schema、加密格式或安裝依賴。

## 發現與處理

1. 原 R10 記錄 Proactor close callback 的 WinError 10054／停機等待問題。本輪在正式一般模式以連線 RST 重現另一個 Proactor 問題：`IocpProactor.accept`／`finish_accept` 拋 WinError 64，接著無法接受新連線。該輪 Ctrl+C 本身正常結束；不將兩個錯誤混寫成同一個重現結果。
2. `app/launcher.py` 的 Windows 正式入口現在使用 Selector，與原 Uvicorn 開發 worker 的策略一致；離開 `serve()` 即恢復呼叫者原政策，匯入 app、`--check` 與非 Windows 不改政策。不修補 stdlib／傳輸私有方法、不隱藏 asyncio 例外、不放寬停止驗收。
3. 正式程式副本沒有 `.git`／`tests` 等目錄時，Uvicorn 將不存在的絕對排除路徑當 glob，會使啟動失敗。現在只傳入實際存在的排除目錄，仍保留固定 app 監看範圍與資料／venv 排除設定。
4. 檔案監看已觸發、但 Windows 舊 worker 未完成停止的重載問題，改由 `app/windows_reload.py` 以 spawn Event 通知自己的 worker 設定 `should_exit`，等待正常 lifespan 與程序結束後，才用同一保留 socket 啟動替代 worker。沿用 Uvicorn 檔案監看與 spawn／socket handoff，不送廣播 Ctrl+C、不以 terminate／kill 取代正常重載。
5. 使用者 Ctrl+C 同時抵達父程序與 worker 時，父程序的 Event 可能先設定 `should_exit`；第一個 console 訊號不能因此被誤當第二次強制退出。adapter 保留 Uvicorn 的訊號記錄與真正第二次 Ctrl+C 語意，避免第一下就取消 lifespan。
6. 完整回歸曾捕捉 worker 已正常結束、但監督程序未在五秒內退出。同步 WatchFiles 預設在 Rust 最多等待 5000 ms；Windows adapter 將**監看器閒置等待**縮為 250 ms，讓 Python 有機會及時處理 console 訊號，維持原檔案通知／過濾及五秒停止驗收，不是把停機期限加長。
7. 縮短等待後仍有偶發未及時停止，因此監督程序另外在啟動後註冊 Windows 原生 Ctrl+C 控制處理器，在控制執行緒直接設定 watcher／worker 的停止 Event，不只依賴主執行緒的 Python 訊號處理。只處理自身收到的 Ctrl+C，不發送訊號、不吞其他 console 事件，離開時解除註冊；監督迴圈以 `finally` 執行正常 shutdown，錯誤也不跳過清理。原生處理器註冊／解除、非 Ctrl+C 事件、錯誤路徑與真正 OS 事件均有回歸。

`windows_reload.py` 明確依賴鎖定版本的 `uvicorn._subprocess`、`Server` 訊號狀態及 reloader 介面。升級 Uvicorn 時必須審查並重跑本文件的實際 spawn／重載／停止測試，不只看單元測試或版本號。

## 自動驗證範圍與安全界線

- `tests/test_windows_lifecycle.py` 執行 module／batch × 一般／開發四種入口，每種兩輪停止與同 port 重啟。一般模式使用工作區正式入口；開發模式使用 app 與 batch 的副本，避免透過改動原 app 觸發使用者現有服務的監看器。
- 每例在 `data/windows-lifecycle-*` 建立獨立 SQLite 與假專案、備註、加密帳號；先指定 DB 路徑才啟動。重載副本只複製小型 venv 啟動器／設定，唯讀使用既有依賴，不安裝套件、不更動原 `.venv` 或正式 DB。
- `tests/windows_console.py` 以 base Python 在 **NEW_CONSOLE、隱藏視窗**啟動，先核對主控台只有控制器自己，才建立測試程序。Windows venv redirector 會多出一個程序，因此不拿它當主控台控制器。沒有附加到使用者的既有終端機。
- 正常停止送出 Windows `CTRL_C_EVENT`，不是 `terminate()`／`taskkill`。batch 若詢問是否中止，輸入 N 讓停止後的正常退出碼流程完成。控制器不使用可繼承的忽略 Ctrl+C 旗標。
- 每輪送 64 次、最多 8 條並行的假資料 GET／RST，重設連線後仍須 ready。開發模式另外變更**副本**的 probe 檔，確認新 worker PID、重新就緒、舊解鎖 session 失效。
- 可加獨立 Chromium 真正頁面導覽與取消，僅連線該測試 origin、先核對假專案名稱，不連外網或接手使用者開啟的 Chrome。先關閉測試瀏覽器，再測停止。
- Ctrl+C 後 **5 秒內**必須正常退出，輸出含 application shutdown complete、沒有 traceback／WinError／callback error，沒有強制清理。超時或錯誤一律失敗；只對本輪明確建立的測試程序樹做失敗清理，不能把清理算通過。
- 停止後同 port 可重新綁定，DB 位元組不變、`integrity_check` 正常，以原假主密碼仍能解密帳號；確認 shutdown 日誌與密碼不出現在日誌。正常結束自動移除該例精確的私有目錄，不批次刪除 data。

## 重跑

先依 [本機維運](local-operations.md) 建立含測試依賴的 Python 3.12 環境。純 HTTP／socket／OS console 與 adapter 回歸：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_launcher.py tests/test_windows_lifecycle.py tests/test_windows_reload.py -q --basetemp=data/pytest-windows-lifecycle
```

另跑真實 Chromium 導覽，需要既有 [瀏覽器測試依賴與引擎](browser-regression.md#重跑)。設定如下，再執行上面命令：

```powershell
$env:PROJMEMO_WINDOWS_BROWSER = '1'
```

未設定此旗標時只驗證原生 HTTP／RST、重載與 Ctrl+C，不聲稱已跑 Chromium。啟用後缺 Node、套件或引擎應失敗，不自動下載、不回退為假通過。可用獨立驗證 venv 的 Python 路徑替換 `.venv`，不需修改程式。CI 的一般 pytest 會包含原生生命周期與 adapter 測試；Chromium 加強路徑需另明確啟用。

## 適用限制

Selector 在 Windows 有 512 sockets 上限，不支援 asyncio subprocess／pipe；目前個人本機服務不使用這些能力，不可將此策略直接擴張為多人／高併發版。直接執行 `uvicorn app.main:app` 不會經過這個 launcher 的政策與 Windows 重載 adapter；請使用 `run-local.bat`／`run-dev.bat`。

自動驗收使用真正 OS console 事件，但不是使用者親手在特定 Windows Terminal／PowerShell 視窗按鍵或關閉視窗的驗收；不認證關窗 X、強制終止、斷電、外部 DB writer 或所有 Python／Uvicorn 版本。任意長交易不保證五秒內完成；不要把再次 Ctrl+C 的強制退出當成正常停止。若希望補人工觀察，可在隔離資料服務的終端機按一次 Ctrl+C，確認正常停止及重新啟動；不必操作正式資料。

## 2026-10-20 最終結果

完整 Python **720 passed／1 個既有 Linux 專用 skip**，本輪新增 17 項；Node **78 passed**，保留原兩個第三方棄用警告。最終完整回歸啟用 `PROJMEMO_WINDOWS_BROWSER=1`，正式 module／batch × 一般／開發四路徑，每種兩輪：共八輪原生 Ctrl+C／同 port 重啟、八輪獨立 Chromium 導覽／取消，開發兩路徑共四次真正檔案重載。DB 位元組、完整性、原主密碼解密、解鎖失效與正常 lifespan 均通過；沒有強制清理被算作成功。

首輪完整回歸曾有 **715 passed／1 failed／1 skip**，worker 已退出但監督程序延遲，該輪不算通過；新增原生控制處理與註冊／解除回歸後才得到上述最終結果。這不是既有 Playwright 76 項全套重跑，也沒有重驗本機 Firefox、真正桌面縮放／OS 剪貼簿或 Linux／CJK。來源／catalog、pip check、Git whitespace 與本機文件連結亦通過，正式資料及既有服務未作為測試目標。

技術依據：[Python Windows event-loop 限制](https://docs.python.org/3.12/library/asyncio-platforms.html)、[Windows console Ctrl 事件](https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent)／[原生控制處理器](https://learn.microsoft.com/en-us/windows/console/handlerroutine)、[Uvicorn 鎖定版本的 reloader](https://github.com/Kludex/uvicorn/blob/0.34.2/uvicorn/supervisors/basereload.py)、[WatchFiles 的等待參數](https://watchfiles.helpmanual.io/api/watch/)。
