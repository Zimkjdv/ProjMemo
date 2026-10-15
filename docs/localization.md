# 繁中／英文 catalog 維護

繁中以來源字串為基準，英文在 `app/locales/en.json`；少量原本為英文的選項由 `i18n.ZH_MESSAGES` 提供繁中對應。使用者專案名稱、說明、備註、帳號與匯出原文不自動翻譯。

在已安裝 runtime 的環境可從任意工作目錄呼叫：

```powershell
.\.venv\Scripts\python.exe scripts/check_catalogs.py
```

成功 exit 0；缺漏、未使用、重複 JSON key、空翻譯、佔位符／format spec／conversion／重複次數不一致、孤兒單數變體、未登錄動態訊息或宣告已過期時 exit 1。工具只讀 Python／Jinja AST 與 catalog，不 import app、不開 DB、不掃描使用者資料。

## 修改流程

1. 新 UI 文字透過模板 `t('來源')`；JS 的使用者提示從模板翻譯後的 data attribute 傳入，不另藏一份中文 fallback。後端可顯示的錯誤亦加入英文對應。
2. 新增英文 key，保留相同的具名佔位符；可調整先後順序，不能改名、遺漏、重複或改變格式。需要單數時用 `::one`，必須有原 key 與 `{count}`。
3. 文字改名或移除後執行檢查，人工確認 unused 不是間接使用再刪除；不要用整批刪除腳本掩蓋問題。
4. 動態 numeric f-string 可由同模組常數解析（如主密碼最短長度）。無法靜態解析的錯誤，需在 `catalog-policy.json` 登記來源、原 pattern、正規化目標與原因；程式內 `translate_error` 仍須真的完成正規化，不是加一條白名單就有翻譯。登記過期會失敗。
5. `identity_keys` 僅限目前使用、刻意不改英文的英文來源標籤；不能用來忽略缺漏中文。確有外部相容用途的 unused key 可放 `retained_unused`，需理由，來源重新使用或 key 移除後必須撤銷例外；預設為空。
6. 執行 checker、`tests/test_catalog_checks.py` 與既有 `tests/test_i18n.py`，再跑完整 Python／Node 回歸，確認使用者原文與語言切換沒有改變。

## 靜態檢查界線

工具檢查 Jinja 的常數／靜態分支、未包裝的中文文字，Python 翻譯呼叫／錯誤／訊息 dict／指定字串與 options。unused 採 app Python／Jinja 字串庫作保守候選判斷；排除 Markdown／PDF 固定文件標題，不代表可證明每個執行分支一定用到所有 key。任意組字、外部動態內容與 JavaScript 新增提示仍需 code review／互動驗收；不能把 checker 通過當作完整雙語 UI 驗收。

這次移除 24 個舊 UI 遺留 key，保留仍使用的動態密碼長度訊息，補上「尚未設定密碼保管庫」英文。正規化錯誤與英文來源 identity 均明確記錄；未翻譯任何使用者資料。
