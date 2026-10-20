# R08 桌面瀏覽器回歸

測試在獨立 Chromium／Firefox 引擎執行，不以 DOM 替身、TestClient 或 Header 測試代替瀏覽器。`tests/browser/package-lock.json` 固定 Playwright 1.64.1 與 npm integrity；僅開發／CI 使用，不改應用 runtime。原工作區每語言六項，R09 追加兩項、R10 再追加搜尋與原生交接兩項：兩引擎共 40 項，啟用 Edge 則 60 項；零自動 retry，任一失敗即非通過。歷史 run 數量不追改。

## 重跑

先使用 Python 3.12 的含雜湊測試鎖建立開發 venv，Node 版本依 CI 基線。Windows：

```powershell
npm ci --ignore-scripts --no-fund --prefix tests/browser
npm exec --prefix tests/browser -- playwright install chromium firefox
$env:PROJMEMO_TEST_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm test --prefix tests/browser
```

Linux 改用 `.venv/bin/python`，安裝引擎時使用 `playwright install --with-deps chromium firefox`。不設定 `PROJMEMO_TEST_PYTHON` 時預設使用專案 `.venv`；也可指定獨立測試 venv。可加 `-- --project=firefox` 或 `-- --headed`；headed 會開啟測試瀏覽器，並非日常執行需求。

測試自行啟動 Python fixture，先覆寫 DB 路徑為新建 `data/r08-browser-*` 私有目錄，再匯入應用。socket 綁定 loopback port 0 並保留到 Uvicorn 接手，不探測後重綁、不重用現有服務、沒有可指向正式主機的 base URL 參數。每例建立 55 筆假備註和一條 example.invalid URL，結束以 stdin EOF 正常關閉並清除私有 DB／日誌／復原點。若程序被強制終止可能留存目錄，先確認測試程序結束再刪除該輪精確路徑，不能批次清除整個 data。

R10 補強 fixture 結束順序：先關閉該例測試頁面，再讓 `appURL` 的 EOF 停機流程執行；另先確認偏好已保存及重設頁載入完成，不以尚未執行 defer 腳本的 DOM 當作偏好持久化成功。只關頁仍不足以解決本機逾時，階段診斷抓到 Python 3.12 Proactor 的 `_call_connection_lost` 在 `socket.shutdown` 拋出 WinError 10054、尚未執行 `_server._detach()`，伺服器停在 shutdown。

因此 Windows **測試服務程序**改用 Selector event-loop policy；Linux 不變，不安裝／修補依賴，不更動正式 launcher 或 app 的 loop／timeout。保留 5 秒停止判定、零 retry、EOF／停機／暫存清理階段診斷，任何清理失敗仍算失敗。Selector 下的互動結果不冒充正式 Proactor 入口的連線重設／停機容錯驗收；後者在 Roadmap 另列補驗，未在 R10 擅自更改正式執行策略。

上述是 R10 當時的界線。2026-10-20 已另外以正式 launcher 完成 Windows 補驗並加入 Selector／私有 Event 重載處理，沒有拿本 fixture 的結果代替；原始待辦移至 Changelog。四種正式入口、真正 OS Ctrl+C、真實檔案重載與獨立 Chromium 加強路徑見 [Windows 啟停驗證](windows-lifecycle.md)。本文件的歷史 R10／R13 輪次不追改成當時已完成正式補驗。

## 驗收內容

| 每語言／引擎案例 | 檢查 |
| --- | --- |
| 無 JavaScript | 原生分頁、伺服器錯誤回填、修正後成功 |
| 專案表單 | 超長名稱 400、保留說明、錯誤摘要焦點／aria-invalid、token 負責人／標籤、重試建立、原生雙語切換 |
| URL 表單 | 瀏覽器接受但伺服器拒絕的 userinfo URL、回填後重試、編輯、Escape／取消保護、筆數未重複 |
| 內容工作區 | 卡片／明細、10／20／50、未存草稿取消／確認換頁、請求失敗保留 DOM／原頁次、重試、語言切換取消保留原文 |
| 備份 | 真正 SQLite 下載、錯誤上傳、原資料仍在、確認還原舊備份後新增專案消失 |
| 保管庫 | 假主密碼設定、假帳號加密保存、顯示／鎖定、錯誤解鎖不回填、正確重試；一般 Markdown 不含明文，瀏覽器儲存不含假密碼 |
| R09 生命週期 | 假資料封存、分類入口、垃圾桶、復原到已封存、取消封存、錯誤名稱拒絕並重新確認、永久刪除及復原點列表 |
| R09 無 JavaScript | 原生展開確認、完整名稱／勾選、POST 封存及管理頁狀態更新 |
| R10 搜尋與進度 | 五類內容搜尋、負責人／完整標籤／未完成交接的交集、卡片／明細、偏好還原／明確空值／重設、直接勾選交接；1280／1440／1920 寬度無整頁橫向溢出，進階條件維持全寬而非被 flex 擠成側欄 |
| R10 原生交接 | 無 JavaScript 新增／切換未完成、備註 10 筆換頁、完成最後一項後空結果與全部數量，切回全部可見已完成內容 |
| R11 備份預覽 | 雙語上傳比較、取消不建復原點、token 不進 URL／storage、1280／1440／1920 寬度及純假資料截圖；原備份回歸改為預覽後明確確認，另驗語言切換返回可 GET 的備份首頁 |
| R11 原生還原與清理 | 無 JavaScript 勾選／輸入 RESTORE 還原；以相容 API 在私有 fixture 建三份有效快照，存策略不刪除、預覽兩份候選、取消不刪、DELETE 確認後只保留一份 |
| R13 主密碼更換 | 繁中／英文、JavaScript／原生提交，錯誤不回填三個密碼與勾選，正確重試後鎖定、新密碼可解鎖而舊密碼拒絕；跨分頁遮蔽及更換前快照下載。舊備份實際還原與競態／交易故障由 Python 隔離測試涵蓋 |

瀏覽器網路限制只允許當例 loopback origin；不造訪 example.invalid，不連外部帳號。失敗上下文只含假資料，存於忽略的 `data/r08-browser-results`；關閉 trace／錄影／自動失敗截圖，R09 案例另明確保存管理頁與垃圾桶確認頁的純假資料截圖供視覺檢查。CI 不上傳資料 artifacts。安裝依賴／引擎本身需要網路。

## 驗收界線與原始規劃

使用 1440 × 1000 headless 桌面 viewport。引擎為 Chrome for Testing 156.0.8078.4（Chromium revision 1248）與 Firefox 157.0（revision 1555）。本機 Chromium 12 項通過；Firefox 兩次啟動均發生 `spawn UNKNOWN`，未執行的測試不算通過，沒有調整或繞過系統安全政策。

另支援已安裝 Edge：設定 `PROJMEMO_TEST_EDGE=1` 後可用 `-- --project=edge` 執行 12 項；沒有 Edge 不自動下載或略過。Windows CI 啟用 Edge（共 36 項），手動啟用 Linux 時跑兩引擎（24 項）；依使用者要求，Linux job 現在須於 Run workflow 勾選 `run_linux`，不在 push／PR 自動執行。實際平台結果須以該提交 run 為準；這不等同已驗證所有已安裝瀏覽器版本、真實 Windows 125%／150% 縮放、OS 剪貼簿或完整視覺可讀性。

`8b979b8` 的 [run 38709940208](https://github.com/Zimkjdv/ProjMemo/actions/runs/38709940208) 最終成功：Windows 三瀏覽器 36 項、Python 462 項（1 個 Linux 專用 skip）、Node 66 項；Linux 兩引擎 24 項、Python 452 項（11 個 Windows 專用 skip）、Node 66 項及 CJK glyph。保留既有兩個第三方棄用警告。本機 Edge 另有 12 項通過；Firefox 的本機啟動限制仍如實保留，由真正 Windows runner 的 Firefox 結果補驗，不把本機未執行算成功。

來源 `3e482af:ROADMAP.MD` 的原條目保留如下，避免拆分時遺失範圍；最後一句當時依使用者要求與 R06-B 一起保留待驗收，不因該輪瀏覽器測試勾選完成；後續補驗結果見下段：

> 補表單錯誤等回歸及更多標準桌面瀏覽器的完整互動驗收；過期 session、重複解鎖、延遲 reveal、CSRF、完整備份驗證及還原異常流程已有隔離測試。來源政策與原生表單的衝突已修正，並完成實際瀏覽器中英文切換驗證；Header／token 測試不能取代瀏覽器驗收。補實際 Windows 瀏覽器剪貼簿貼回驗收，內嵌瀏覽器的虛擬剪貼簿與頁面 Clipboard API 無法互通。

既有過期／延遲 reveal／CSRF／還原異常的隔離 Python／Node 測試仍保留；本套瀏覽器案例不是每個異常分支的替代品。R06-B 系統剪貼簿已於 2026-10-16 另以使用者實際 Windows Chrome 手動貼回、四類原文逐字比對與 32 組故障提示補驗，原句於 Changelog 完整勾選移錄。R06 真正 Chrome 125%／150% 縮放及人工鍵盤錨點亦於同日另行完成並還原 100%，方法及範圍見 [實機操作](desktop-acceptance.md)。這不表示本套 headless CI 取得 OS 剪貼簿或真正桌面縮放驗收能力，兩者仍須分開執行。

官方工具規範：[Playwright CI](https://playwright.dev/docs/ci)、[瀏覽器引擎](https://playwright.dev/docs/browsers)。fixture 刻意不採用可重用的既有 webServer，避免本機資料混入測試。

## R13 本機補驗（2026-10-20）

Chromium／Edge 全套各 38 項，共 **76 passed**；R13 新增 8 個雙語 × JavaScript／原生 × 兩引擎案例，完整驗證錯誤清空／重新確認、正確重試、成功後鎖定、舊密碼拒絕與新密碼解鎖、更換前復原點列表／下載。啟用 JavaScript 時另驗已揭露密碼的分頁在更換後遮蔽並停用揭露，無 JavaScript 不宣稱即時遮蔽。原生命週期、搜尋、備份清理、草稿、編輯／匯出與分頁回歸保留，未增加 retry 或放寬停止期限。

完整 Python **703 passed／1 個既有 Linux 專用 skip**（R13 新增 28 項）、Node **78 passed**，保留原兩個第三方棄用警告。檢視展開且密碼空白的繁中／英文純假資料截圖；未操作正式 DB、既有備份或原 `.venv`。本輪沒有重跑本機 Firefox、真正 Windows 縮放／剪貼簿或 Linux／CJK 手動 gate；Windows 測試服務仍沿用上述 Selector 界線，不代表正式 Proactor 補驗完成。操作、原主密碼必要性與舊備份復原見 [主密碼更換](master-password-change.md)。

## R12 本機補驗（2026-10-19）

Chromium／Edge 全套各 34 項，共 **68 passed**；其中 12 個新案例驗證雙語模板套用／取消、注入防護預覽、過時／失敗回應保留草稿、備註換頁重新綁定、獨立文件語言／章節下載及無 JavaScript 模板／原生預覽。原備份／還原、清理、生命週期、搜尋、草稿、分頁及保管庫流程仍通過，維持零 retry 與原停止期限。全套 Python **675 passed／1 個既有 Linux 專用 skip**，Node **78 passed**；追加原生匯出錯誤保留選項後，R12 16 項另再通過，不重複累加。

檢視純假資料編輯／匯出截圖及雙語各 7 頁 PDF 渲染，未操作正式資料庫、既有復原點或原 `.venv`。本輪沒有重跑本機 Firefox、真正 Windows 縮放／剪貼簿或 Linux／CJK 手動 gate；初期受限環境的失敗輪次不列為成功。操作與 Mermaid 安全設計見 [編輯與匯出](editing-export.md)。

## R11 本機補驗（2026-10-19）

Chromium／Edge 原全套加 R11 三類流程共 52 項通過；預覽頁語言切換的安全 GET 返回另新增並通過 4 項，共 56 個不同案例。最後的返回標記讓既有 `language.js` 使用正確備份首頁，不只修改 hidden input 後便假定前端不會覆寫。失敗輪次不計入成功，未改既有 5 秒停止期限或零 retry。

檢視純假資料的繁中還原比較及英文清理截圖；R11 預覽在兩語言／兩引擎的 1280／1440／1920 寬度無整頁橫向溢出。這是 headless 桌面與欄位操作驗證，不冒充重新完成 OS 剪貼簿、真正 125%／150% 縮放、本機 Firefox 或 Linux／CJK 補驗。截圖只存忽略的測試輸出目錄，不提交任何資料庫或敏感內容。
