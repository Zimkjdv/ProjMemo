# ProjMemo Roadmap

更新日期：2026-10-16。初始盤點基準：`d4721a4`；專案內頁 UI 補充分析基準：`6c05ec0`。依程式、模板、測試與 Git 紀錄分析；後續實作完成即移至 [CHANGELOG.MD](CHANGELOG.MD)。使用說明見 [README.md](README.md)。

狀態格式：待實作或待驗收的工作使用 `- [ ]`；完成實作與該項驗證後，搬至 Changelog 時保留項目 ID，改用 `- [x]`。部分完成只搬移已完成的部分，剩餘工作與驗收限制繼續在本文件追蹤，不將整批直接勾選為完成。

歷史追溯：截至 `9824ed3` 的 6 個 Roadmap 版本已逐版核對，原始待辦與驗收清單見 [Changelog 歷史清單](CHANGELOG.MD#歷史-roadmap-勾選清單追溯2026-10-14-補齊)。後續 R06-C 完成時，亦完整搬移 `28fb155` 版本的 7 條原勾選項目與驗收；R06-D 保留 `5fe6055` 的全部 6 條原文，當時未完成的真正縮放驗收於 2026-10-16 補驗後才勾選。保留 ID、來源及歷史界線，不以成果摘要取代。

## 定位與架構判斷

維持「個人部署、桌面操作、Python .venv、SQLite」定位。現有 FastAPI + Jinja2 + 原生 JavaScript 足以支援此規模；目前沒有為了整理架構而改寫 Vue、導入 Redis 或更換資料庫的必要。Docker 待本機功能與資料復原流程穩定後再做；多人協作與手機版另行規劃。

現有優點包括：SQL 參數化、交易提交／回復、Markdown HTML 清理、一般匯出不含實際密碼、敏感匯出另外檢查政策與解鎖、SQLite 快照及還原前備份、雙語介面，以及共用表單 DOM 的卡片／明細切換。優化時需保留這些行為。

| 層次 | 現況 | 改善方向 |
| --- | --- | --- |
| 路由與流程 | `app/main.py` 僅組裝應用；八個 router（含健康探針）與八個 service 分開，列舉／匯出資料共用 | 新功能維持邊界及 HTTP／交易回歸，不重回單一大型入口 |
| 資料 | SQLite 八張業務表與遷移紀錄表，schema v4；七個量測索引、生命週期索引與有界鎖等待 | 保留升級回歸與個人版限制，不把索引等同整頁效能問題已解決 |
| 保管庫 | `app/vault.py` 處理 Argon2id、AES-GCM 與程序內 session | 強化輸入邊界、過期清理及單程序限制 |
| 匯出／備份 | Markdown／PDF／備份獨立模組，共用 `ProjectData` 與列舉；真實 PDF／抽字／跨頁回歸及本輪視覺驗收完成 | 維護字型／長文件回歸，換平台或字型時重新看頁面 |
| UI | Jinja2 模板、集中 CSS、功能別 JS | 統一表單回饋、選單操作、長內容及桌面密度 |
| 文件／品質 | README、安全說明、Python／Node、catalog／格式檢查及含真實瀏覽器／PDF 的 Windows → Linux／CJK CI；系統剪貼簿與 Chrome 真正縮放已另驗收 | 維護既有回歸；換平台、字型或瀏覽器後按指南重驗 |

## 優先級與執行順序

- **P0：資料與本機請求保護**。三個交付項目已移至 Changelog；後續部署仍須遵守單程序、本機存取限制。
- **P1：可靠性與日常操作**。在核心保護之後分批交付。
- **P2：功能擴充與體驗提升**。按實際使用需求選取，不代表全部必做。
- **Later：部署與協作**。有前置條件，不列為目前個人版必備功能。

R01 至 R10 的實作與各自驗收已交付並移至 Changelog，包含 R06-B 真正系統剪貼簿與 R06-D 的 Chrome 125%／150% 實機驗收；不再保留 R06／R08 未完成條目。R10 測試發現的 Windows Proactor 停機相容性另列下方補驗，不把測試專用 Selector 結果冒充正式入口驗證。後續依實際需求選取 P2，Docker 另行安排，不自動開始擴充或部署。UI 伺服器端分頁已於 R05 上線，實作與量測見 docs/note-paging.md，不將原 R03 的評估紀錄冒充當時已上線。

## P1：可靠性、架構與桌面操作

R03 原規劃的遷移、路由／服務分層、量測後索引／鎖策略及 UI 分頁評估已完成；原始勾選文字保留於 [CHANGELOG.MD](CHANGELOG.MD)。實作與維運規範見 [程式架構](docs/architecture.md)、[升級復原](docs/database-migrations.md)、[量測與評估決策](docs/performance-r03.md)。實際 UI 分頁已於 R05 交付，R10 只保留搜尋及其他交接效率擴充。

R04 已隨 R06-B 完成，期限、session 清理及同步驗收紀錄移至 [CHANGELOG.MD](CHANGELOG.MD)，安全界線見 [保管庫安全說明](docs/vault-security.md)。

R06 桌面 UI 已完成：長欄位展開、明細行內編輯、首頁偏好、備註分頁及 Chrome 真正 125%／150% 縮放驗收均已交付。剩餘三條原驗收完整改為 `[x]` 移入 [CHANGELOG.MD](CHANGELOG.MD)，不再列為待辦。現行規格、原分析表、分批取捨與 `af04427` 歷史快照見 [桌面 UI 設計與驗收](docs/desktop-ui.md)；可重跑方法及實機結果見 [實機驗收指南](docs/desktop-acceptance.md)。重複計數保留兩處，未擴充手機需求。

R07 四項實作與整體驗收已逐項交付，原始五條 checkbox 完整移至 [CHANGELOG.MD](CHANGELOG.MD)。現行規範見 [本機維運](docs/local-operations.md)、[依賴與安全掃描](docs/dependencies.md)、[健康與安全日誌](docs/operations-health.md)。不將 Windows／Python 3.12 的驗證擴大為已認證 Linux／Docker。

- [ ] **Windows／Python 3.12 Proactor 連線重設與停機補驗**：R10 假資料瀏覽器服務捕捉到 `_ProactorBasePipeTransport._call_connection_lost` 的 WinError 10054，回呼在 `socket.shutdown` 拋錯、尚未執行 `_server._detach()`，接著停在伺服器 shutdown。本輪僅將 Windows 測試服務改用 Selector，未修改正式 launcher／app 或放寬停止逾時。後續以正式啟動入口搭配隔離 DB 重現快速導覽／取消請求及停止，再評估 Python 修正版或執行策略；不把測試程序的環境調整當作正式容錯已修復。階段診斷及驗收界線見 [瀏覽器回歸](docs/browser-regression.md)。

R08 的文件、Markdown、catalog、CI、真實瀏覽器／PDF、Linux／CJK 補驗及 R06-B 系統剪貼簿均已完成，原條目與驗收移至 [CHANGELOG.MD](CHANGELOG.MD)，包含歷史四種改寫條目的完整原文。2026-10-16 使用者在實際 Windows Chrome 親手複製／貼回四類原文並逐字比對，另完成 32 組雙語／兩檢視的失敗提示；不是工具虛擬剪貼簿或成功回饋的替代驗收。規範見 [瀏覽器回歸](docs/browser-regression.md)、[實機驗收操作](docs/desktop-acceptance.md) 與 [PDF 驗收](docs/pdf-verification.md)。Linux 仍維持手動 `run_linux`；R06 真正縮放另於本日實測並取得人工鍵盤確認後結案，不與 R08 混算。

## P2：依需求擴充

R09 專案封存／垃圾桶／復原及先快照再永久刪除已完成；原規劃與驗證紀錄移至 [CHANGELOG.MD](CHANGELOG.MD)，操作與資料／密碼界線見 [專案生命週期](docs/project-lifecycle.md)。以下僅保留未完成項目。

R10 內容搜尋、獨立負責人／標籤篩選、交接完成度與未完成檢視已完成；原規劃及驗證移至 Changelog，規則與實測見 [搜尋與交接效率](docs/search-handover.md)。FTS 已經過指定樣本的語意評估，依短中文需求及個人版規模決定本輪不導入，不宣稱現有 B-tree 最佳化所有子字串。

| ID | 待辦 | 驗收方向 |
| --- | --- | --- |
| R11 | 備份操作體驗 | 還原前預覽專案數、版本、保管庫狀態及替換範圍；備份保留策略由使用者設定，不默默刪除復原點；另評估完整備份加密 |
| R12 | 編輯與匯出 | Markdown 預覽、模板、選擇匯出章節及中英文文件標題；Mermaid 需安全渲染設計，不開放任意 HTML／腳本 |
| R13 | 主密碼更換 | 必須知道原主密碼；新 salt／金鑰、交易式重新加密、先備份、失敗回復、撤銷全部舊 session；不提供繞過舊密碼的解密「重設」 |
| R14 | 個人版本紀錄 | 評估非敏感內容修訂／差異與復原；Git 同步須另設敏感資料排除規則，不將整個資料庫或含密碼匯出推到 Git |

## Later：有條件的後續階段

- [ ] **Docker 個人版**：R01／R02 與本機穩定性完成後導入；持久化 volume、非 root、CJK 字型、單 worker、健康檢查、升級與還原演練，預設仍不公開服務。
- [ ] **多人協作版**：需求確認後另設登入、權限、每人 session、審計與資料隔離；不能只把目前服務改綁 `0.0.0.0` 就當作協作版。
- [ ] **手機版**：留到協作版再評估，不占用目前桌面個人版開發優先級。

## 本次分析的界線

本文件保留尚未完成的工作；已交付細節見 Changelog。未執行惡意備份資源壓力測試；R08-E 已以純假資料完成完整 PDF 生成／抽字／渲染及本輪 Windows 逐頁視覺驗收，範圍與重跑規範見 docs/pdf-verification.md。未開啟或修改使用者的實際 SQLite 資料。

2026-10-14 UI 補充分析核對附件、原始碼、現有測試與 Changelog；R06-D 當時保留真正 Windows 縮放待補驗，2026-10-16 才在實際 Chrome 125%／150% 完成並還原 100%。R06／R04 各批均以隔離假資料驗證，未操作真實帳號。附件截圖不能用來精確量測實際瀏覽器字級與對比。既有測試紀錄以 Changelog 為準，下列數量是早期分析當時的基線，不是目前測試總數。

2026-10-13 基線驗證：既有 Python 測試 14 項通過、Node 測試 5 項通過。Python 有一項 Starlette 使用 AnyIO 舊別名的棄用警告，列入依賴更新檢查；通過既有測試不代表本文件列出的缺口已獲覆蓋。
