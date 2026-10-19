# Markdown 編輯與可設定匯出（R12）

範圍：本機個人桌面版，不改 SQLite schema、密碼格式或部署方式。原規劃為 `1746394:ROADMAP.MD` 的 R12：Markdown 預覽、模板、選擇匯出章節及中英文文件標題；Mermaid 需安全渲染設計，不開放任意 HTML／腳本。

## 編寫與預覽

專案內新增／編輯備註共用一組 Markdown 工具：先選模板，再按「套用模板」；有任何現存文字（包含空白）都須確認才覆蓋。模板只填 Markdown 內容，不更動標題、類型、優先級或已保存紀錄。內建一般備註、已知問題與替代方案、部署與回復、交接備註各有繁中／英文版本，不插入真實帳號或讀取保管庫。沒有自訂模板執行、Jinja 展開或 Shell 執行功能。

「預覽 Markdown」只送出目前 Markdown 到同來源的 `/editor/preview`，不自動儲存或在輸入時自動傳送。最多 100000 個 Unicode 字元、拒絕 NUL，空白預覽允許。失敗保留原草稿；10 秒逾時、編輯／重設草稿或較新的預覽會使舊結果失效，備註換頁後重新啟用，沒有重複掛載。草稿與預覽均不存入 localStorage／sessionStorage、DB、檔案或 URL；既有頁面離開／收合取消保護維持。

預覽使用既有 Markdown extensions 與 nh3 allowlist，再移除所有導覽目標及屬性。HTML 僅存在無權限 `sandbox` iframe，內含 `default-src 'none'`、禁止表單與 base、僅允許固定內嵌樣式的 CSP；不允許圖片、SVG、iframe、腳本、事件或可點擊外部連結。這是應用層與瀏覽器的分層限制，不是能抵禦任意同帳號惡意程序的隔離。

停用 JavaScript 時，備註中的預覽按鈕會在新分頁顯示安全結果，原草稿留在原頁、不消耗儲存 token。`/editor` 是獨立暫存編輯工具：可載入四種模板、修改、預覽後自行複製回專案；關閉不保存。預覽 POST 仍受來源／CSRF 保護，原生回應另有 CSP sandbox；所有預覽回應 no-store。

不要把實際密碼放在一般備註。預覽不會把普通文字變成密碼欄位；一般備註及其匯出仍是非加密內容。

## 匯出選項

專案右上「匯出專案 → 匯出選項」開啟 `/projects/{id}/export`。文件語言預設跟隨目前介面，但可獨立選繁中／英文；只翻譯章節、固定欄位、列舉及空內容提示。專案名稱、負責人、標籤、備註內的標題、程式碼及使用者原文保持原樣，不做整份文件字串取代。

六個可選章節：專案描述、重要 URL、備註與注意事項、環境變數說明、帳號與存取資料、交接清單。專案名稱與基本 metadata 一律保留，至少選一節；章節順序固定，不受提交順序影響。未知語言／章節及重複選項拒絕處理。未選章節不輸出標題、內容或空白提示，也不經 PDF 內容渲染；選中的章節包含完整內容，不受畫面分頁或篩選影響。格式可選 Markdown／PDF，PDF 保留 CJK 字型、頁首／頁尾及跨頁表格。

新頁面 POST 是唯讀下載，可以連續使用，不套用寫入表單的永久停用鎖。原生 HTML 錯誤保留格式、語言與章節，敏感確認必須重新勾選；API 仍使用原錯誤 JSON。舊的一鍵 `.md`／`.pdf` 與 `/export-with-secrets` 端點、預設混合語系文件、HTTP 契約及 renderer 呼叫方式保留。

## 密碼界線

預設一般匯出只讀帳號 metadata、不載入密文，也不解密。新設定頁的「包含實際密碼」**不是**取消保管庫保護：仍需啟用匯出政策、有效解鎖及當次敏感確認。即使未選帳號章節，選敏感模式仍須通過三道檢查；排除帳號章節時不載入密文、不解密，也不輸出帳號。敏感回應維持 no-store／no-referrer、敏感檔名及文件警告。

環境變數標為 Secret 時不匯出其描述值。若使用者將密碼手動貼入一般備註／其他欄位，系統無法辨識並自動排除；請移至保管庫。匯出會產生本機下載副本，應自行安全保管與刪除。

## Mermaid 安全設計與本輪取捨

本輪交付的是安全渲染**設計**，沒有新增 Mermaid 套件或圖形渲染器。`mermaid` fence 在編輯預覽、既有內容與 PDF 一律當程式碼顯示，Markdown 匯出保留原 fence；外部閱讀器如何處理不受 ProjMemo 控制。

未來若確有圖表需求，採以下啟用條件，不直接把輸出 SVG 塞入主頁：

1. 固定且可離線更新的依賴與安全審查，不在預覽時連 CDN。限制圖形種類、原始字數、節點／邊數、併發及渲染時間，失敗退回原碼。
2. 管理端固定 strict securityLevel、停用互動與 HTML labels；拒絕文件內初始化／設定覆寫、themeCSS、外部資源與 click／回呼等能力。不能只相信套件預設安全。
3. 在獨立、沒有使用者資料或保管庫權限的渲染程序內產生圖形，再以嚴格 SVG allowlist 檢查與隔離顯示；拒絕 script、foreignObject、事件、外部 URI／CSS／字型、超量或不合法幾何。不能把現有 nh3 HTML allowlist 直接放寬成任意 SVG。
4. 顯示端用無同來源／腳本／表單／導覽權限的框架與封鎖網路的 CSP；若採點陣圖輸出，也須限制像素與解碼資源。不得將 Mermaid 的可執行 runtime 放進承載資料的預覽框架。
5. 必須補惡意圖形／設定覆寫、SVG 注入、外連監測、資源上限、語法錯誤與 PDF 圖形退回測試，跨平台驗證後才啟用。

依據 Mermaid 官方 [securityLevel 使用說明](https://mermaid.js.org/config/usage.html) 與 [secure 設定鍵](https://mermaid.js.org/config/schema-docs/config-properties-secure.html)。上面是 ProjMemo 的防禦分層設計，不宣稱單靠 strict 或 iframe 已能消除所有渲染漏洞。實際圖形渲染另列 Roadmap Later，未交付的功能不勾為已完成。

## 回歸方法

- `python -m pytest tests/test_editing_exports.py tests/test_architecture.py`：63 種非空章節組合各跑雙語、原文保留、預覽注入／限制／唯讀、CSRF、原契約及密碼保護。
- 真實 PDF 測試生成雙語長程式碼與跨頁表格，透過 pypdf 抽字、PDFium 逐字邊界／逐頁渲染，再人工檢視輸出；抽字不是視覺驗收的替代品。
- `node --test tests/js/*.test.cjs`：保留原有寫入保護，新增唯讀下載可重複使用的回歸。
- 既有 Playwright 設定加入 `editing-exports.spec.cjs`：雙語模板確認／取消、草稿、過時／失敗預覽、分頁重綁、下載選項與無 JavaScript 預覽。不使用正式 SQLite 或真實憑證。

環境／字型或瀏覽器變更仍需重驗，不將 Windows 測試當作 Linux／CJK 手動 gate 或真正桌面縮放已執行。
