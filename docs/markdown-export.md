# Markdown 匯出契約與回歸

一般欄位（專案名稱／說明／負責人／標籤、URL 標題與備註、環境說明、帳號 metadata、交接文字）視為純文字。匯出會跳脫 Markdown／HTML 特殊字元，避免 `*`、反引號、方括號或 HTML 改變原意。標題／列項的換行合併為空白，描述保留換行但不把純文字條列誤作真正清單。這不修改 DB，也不改變 UI／PDF 取得的原始資料。

只有備註的 `content_markdown` 刻意保留原有 Markdown；其中連結、程式碼與格式不重新跳脫。這不是對整份匯出做 HTML 消毒的承諾，使用其他 Markdown 閱讀器仍須遵守其安全設定。

HTTP(S) URL 的目的地會編碼括號、空白與角括號，保留已存在的 `%` 編碼與 query 語意，避免括號被誤判為連結結尾；不把無效或非 HTTP(S) 的舊資料轉成可點擊連結。表格處理反斜線、直線、HTML、反引號與 CRLF；簡單環境變數名稱保留 code 樣式，複雜名稱改用一般跳脫文字，避免不同 Markdown 引擎對 code span 內反斜線的差異。表格後保留空行，防止下一節標題被吃成第三筆資料。

依據：[GitHub Flavored Markdown 規格](https://github.github.io/gfm/)。回歸以實際 Python-Markdown `tables`／`fenced_code` 渲染後的文字、連結與表格格數為準，不只比對來源字串。

普通匯出不解密密碼；敏感匯出仍需既有設定、解鎖與逐次確認，原始密碼用足夠長的 fence 保留內容，包含空白、換行與反引號。環境變數標為 Secret 時不匯出其描述值，只保留說明／保管位置政策。

`tests/test_markdown_export.py` 涵蓋特殊字元、連結、表格、空章節、完整備註與敏感／普通匯出；HTTP 整合測試確認 UI、Markdown 與 PDF renderer 使用同一份完整投影，不受 UI 分頁限制且不修改 DB。此處 PDF 使用投影替身，不取代 R08 尚待完成的真實 PDF 生成、抽字與視覺驗收。
