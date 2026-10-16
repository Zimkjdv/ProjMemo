# 真實 PDF 回歸與視覺驗收

R08-E 不再只驗證 `%PDF-` 或 renderer 替身。`tests/test_pdf_export.py` 共 15 項（包含原置中常數與三個 glyph 選擇案例）；其餘涵蓋真正 ReportLab 生成／缺字型失敗、pypdf 抽字與 PDFium 每頁渲染。兩個 HTTP 案例另走真實資料載入／AES-GCM 解密與匯出政策，全部使用隔離假資料。

## 覆蓋與邊界

| 範圍 | 斷言 |
| --- | --- |
| 空／混合／長單列／長標題 | 全部六章節、CJK、完整長 URL、90 行程式碼、80 列 Markdown 表格、跨頁重複表頭、末筆交接資料與單列結尾標記 |
| 結構／字型／渲染 | strict PDF parsing、內嵌 TrueType／ToUnicode、實際 regular／bold glyph、無替代或控制字元、每頁不是空白／全黑、可見字元在頁邊界內 |
| 一般／敏感 | 一般忽略傳入的 secret_value；敏感檔需有警告，特殊符號、多行及連續／前後空白不被 Paragraph 壓縮；一般匯出即使解鎖仍禁止呼叫 decrypt |
| 完整 HTTP 投影 | 真正匯出全部 55 筆備註，不因 UI 20 筆分頁裁切；attachment／no-store；預設政策 403、未確認 400、啟用且確認才生成、鎖定 423 |
| 缺字型 | 沒有可用 CJK 字型明確 PDFExportError／HTTP 503，雙語錯誤不含假密碼，不悄悄以缺字字型生成 |

可見字元的幾何與非空白影像檢查不是「排版完美」的自動判定；仍須看渲染頁面確認重疊、跨頁、表頭與閱讀順序。CI 使用相同 PDFium 驗證，但不把雲端生成等同人工視覺審查。PDFium 僅在單一測試程序循序操作，不跨執行緒同時呼叫。

PDF 是閱讀格式，不保證複製後保留每種 tab／CRLF／自動折行；需要可精確還原的純文字時使用 Markdown。PDF 不擴充為完整 HTML／Mermaid 渲染器或英文化文件；這些仍屬 R12。字型必須包含欲顯示字形，本輪不宣稱支援任意 emoji／Unicode。

## 本輪修正

- Markdown／業務 LongTable 允許單列內跨頁，保留重複表頭，不再因一列高於一頁發生 LayoutError；欄寬依實際 frame 內容寬度縮放，避免欄位超出邊界。
- 長專案名稱的重複頁首按量測寬度縮略；正文與 PDF metadata 保留完整標題。備註標題直接使用 keepWithNext，避免只包一個標題的 KeepTogether 阻斷與正文的連結。
- 敏感 PDF 用不可折疊空白保留可見密碼空格，不改 DB／加密值，也不放寬匯出政策。
- 清單符號使用內嵌 CJK 字型，依非零 glyph 順序選擇 `•`、`●` 或 `-`；原本 Helvetica 圓點抽字成 DEL，以及文泉驛缺少 U+2022 而輸出空字元的問題都有回歸。未移除缺字／控制字元檢查，也不將 glyph 0 視為可用字形。

## 重跑及人工檢查

只更新含雜湊測試鎖，runtime `requirements.txt` 不變。先在 Python 3.12 開發 venv 安裝 `requirements-test.txt`；pypdf 6.20.1／pypdfium2 5.14.0 不由日常 setup 安裝，也不被 app import。

本輪由 `.in` 以 pip-tools 7.6.2 重新解析、hash_lock 取得 PyPI SHA-256，再以 `--require-hashes` 安裝及 pip check。pip-audit 2.10.1 對測試鎖執行結果 exit 0，JSON 列出 39 個依賴且均無已知漏洞，包含兩個新增 PDF 套件；鎖有 40 個 pin，其中 packaging 未列於該報告，不能把未列出的項目算本次已掃描。這不是安全保證，也不涵蓋外部 Poppler／OS。對應測試鎖 SHA-256：`f92d467b6d37180fec09ebb1836367c9e7ccf16b7466a5e502af0d3814528dee`。

```powershell
python -m pytest tests/test_pdf_export.py -q
python -m scripts.verify_pdf --output data/pdf-review-NEW --poppler
```

`--output` 必須是不存在的新目錄，禁止覆寫既有資料；腳本不讀 DB，只產生五份固定假資料 PDF、UTF-8 抽字、每頁 PDFium PNG、每四頁 contact sheet 與頁數摘要。`--poppler` 額外要求 PATH 中有 `pdftoppm`，以獨立 Poppler 再渲染每頁；不設定時仍有 PDFium。腳本由專案根目錄以 `-m` 執行。

檢查每一張 contact sheet，再以原頁 PNG 放大有疑慮的位置：六章順序、中文字形／粗體、長 URL／程式碼未裁切、表頭跨頁、長單列接續、頁首與頁尾未重疊、一般無密碼、敏感有警告。換字型／平台不固定二進位 PDF 或像素金樣；必須重新看頁面，不能只比 bytes／頁數。

2026-10-15 本機 Windows／Microsoft JhengHei 樣本：空專案 1 頁、混合 7 頁、超長單列 9 頁、長標題 8 頁、敏感 1 頁，共 26 頁。PDFium 及 Poppler 全部渲染、抽字與幾何通過，逐張 contact sheet 核對全部頁面；沒有裁切／缺字／重疊，重複表頭與長列結尾完整。長標題本身會占多行，續頁與較多留白是分頁的正常結果，不為減頁刪內容。原 12 項 PDF 版本的完整 Python 473 passed／1 Linux 專用 skip、Node 66 passed；後續另加三個 glyph 選擇案例，最終數量以 Changelog 為準，保留原兩項第三方棄用警告。

`254057c` 的 [run 38713819658](https://github.com/Zimkjdv/ProjMemo/actions/runs/38713819658) Windows 全數通過，但 Linux 三項 PDF 字型抽字失敗，不冒稱整個 run 成功。修正後在 Windows 額外載入 Ubuntu 24.04 同版 `fonts-wqy-zenhei 0.9.45-8`（regular／bold 均指定該檔），15 項 PDF 回歸通過，五份 25 頁亦完成自動抽字／幾何／雙引擎渲染。這只是 Windows 上的字型重現，不是 Linux OS 或 Linux 視覺認證。2026-10-15 依使用者要求，Linux／CJK GitHub Actions 當時延至下次補驗，未提前勾選。

2026-10-16 已對修正後 `5d7415671019e83e033105ae02da95d4e91f7455` 手動啟用 `run_linux`：[run 38839868250](https://github.com/Zimkjdv/ProjMemo/actions/runs/38839868250) 的 Windows 與 Ubuntu 24.04 兩個 job 皆 success。Linux 使用上述實際文泉驛字型，完整 Python 466 passed／11 Windows 專用 skip，包含全部 PDF 回歸與必需 CJK glyph；兩瀏覽器 24 項與 Node 66 項亦通過。此為真正 Linux OS 的生成／抽字／PDFium 自動渲染補驗，不挪用 Windows 結果；沒有放寬缺字、控制字元或頁面幾何斷言。Linux 人工逐頁視覺檢查並未於本輪執行，不宣稱所有平台／字型都已獲視覺認證。原 Roadmap 補驗條目完整移入 Changelog，手動 gate 保留。

review 目錄含假敏感資料，與 pytest 暫存一樣只供本機驗證；不提交 PDF／PNG／抽字／DB 或上傳 CI artifact。驗收後先確認程序結束，再精確清除本輪目錄，保留正式資料與備份。

工具依據：[pypdf 抽字限制](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)、[PDFium API／生命週期](https://pypdfium2.readthedocs.io/en/stable/python_api.html)、[ReportLab User Guide](https://www.reportlab.com/docs/reportlab-userguide.pdf)。
