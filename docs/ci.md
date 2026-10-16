# CI 與可重現驗證

`.github/workflows/ci.yml` 在 main push、pull request 或手動執行時檢查程式，不部署服務。依 2026-10-15 使用者要求，push／PR 與預設手動執行只跑 Windows baseline；Linux compatibility and CJK font 須在 Actions → Run workflow 明確勾選 `run_linux`，且 Windows 成功後才執行。延後的修正後補驗已於 2026-10-16 完成，仍保留此手動 gate。Linux skipped 表示該次未驗證，不是成功；不跳過真正 Windows batch／reload 回歸。

目前固定 CPython 3.12.10 x64、Node 24.19.0，runner 為 windows-2025／ubuntu-24.04；應用／測試閉包使用含雜湊的 `requirements-test.txt`，pip bootstrap 另由 `.github/requirements-bootstrap.txt` 釘選並驗證雜湊。升級版本須同時審查鎖與 CI 基線，不能只改版本號後略過回歸。OS runner image 本身會更新，並非整個 OS 的 bit-for-bit 快照。

兩個 job 都執行 pip check、來源檢查、catalog 檢查、完整 Python 及 Node 測試。Python 使用明確隔離 `--basetemp=data/pytest-ci`，所有 app 測試使用 fixture DB；不連真實服務、不讀本機正式資料。Windows 跑真實 batch／normal／reload／port 衝突，Linux 明確略過 Windows 專用案例；Windows-only 的鎖寫入 CLI 不在 Linux 假裝可用。

`data/` 被 Git 忽略，乾淨 runner 並沒有這個目錄；兩個 job 都會在 pytest 前明確建立父目錄，避免本機已有 data 而掩蓋 basetemp 建立失敗。此流程只建立 CI 私有資料夾，不會為了測試初始化正式 DB。

## 格式與靜態檢查

```powershell
python scripts/check_sources.py
python scripts/check_catalogs.py
python -m pytest -q --basetemp=data/pytest-local -p no:cacheprovider
node --test tests/js/*.test.cjs
```

請在已明確安裝測試鎖的開發 venv 執行。來源檢查限定 app／scripts／tests／.github 的程式／模板／樣式／JSON／YAML，不掃 data、venv 或備份；要求 UTF-8、檔尾換行、無行尾空白（接受 CRLF 或 LF），檢查 Python AST、JSON（含重複 key）、YAML 語法及 `node --check`。不執行受檢腳本；空來源目錄與缺少 Node 會失敗，避免零檔案假成功。

這是可立即執行的基本格式／語法政策，不冒充全專案 Black／Ruff／mypy 或 ESLint 深度規則；不重排既有長行與 frozen HTTP 契約。Markdown 刻意的行尾空白不受這個格式規則影響。Node 仍只是開發／CI 需求，不是應用 runtime 依賴。

## 真實瀏覽器回歸

執行中的 job 在 Python／Node 後，以獨立 `tests/browser/package-lock.json` 執行 `npm ci --ignore-scripts`、安裝對應 Playwright 引擎，最後執行互動測試。Windows 另啟用 runner 已安裝的 Edge（36 項），手動啟用 Linux 時安裝瀏覽器系統依賴後執行 Chromium／Firefox（24 項）。不自動略過缺少引擎、不 retry 掩蓋不穩定、不指向外部／正式服務；詳細案例及隔離／清理規範見 [瀏覽器回歸](browser-regression.md)。系統剪貼簿與真實 Windows 縮放不包含在本項內。

## Linux／字型範圍

Ubuntu 安裝 `fonts-wqy-zenhei`，明確指定 `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`。CI 必須成功由 ReportLab 載入實際 regular／bold fallback 字型，確認「專案備註交接清單環境設定」字形存在，不能跳過。另有缺字型明確失敗的隔離回歸。R08-E 起完整 Python suite 另執行真實 PDF 生成、pypdf 抽字、PDFium 每頁渲染／字元邊界、長表格／單列跨頁、程式碼、普通／敏感及真實 HTTP 政策，不能只靠此 glyph 檢查。人工 Poppler 逐頁視覺驗收仍是獨立步驟，見 [PDF 驗收](pdf-verification.md)；雲端不保存或上傳假敏感檔。

此相容性 job 使用相同已鎖閉包測試，未宣稱 Windows 解析的鎖會包含所有 Linux optional extras，亦未宣稱 Linux／Docker 正式部署完成。

## 權限與失敗處理

官方 actions 以完整 SHA 固定，checkout 不保留 credential，token 僅 `contents: read`；不用 `pull_request_target`、不部署、不上傳 data／日誌／DB artifacts。每個 job 20 分鐘上限，同一 ref 的新 run 會取消舊 run。workflow 不更改 branch protection；若要把它設為合併必要檢查，需由擁有者另外設定。

首次推送 workflow 才能有真實 GitHub run；本機測試成功不算雲端 CI 成功。若失敗，依 run／job 的失敗步驟修正，再對新的 commit 核對，不能把 skipped／queued 當成通過。每次驗收紀錄寫入 CHANGELOG 並提供 run URL。

官方依據：[GitHub Python CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)、[checkout 權限](https://github.com/actions/checkout/tree/v6)、[Node syntax check](https://nodejs.org/api/cli.html)、[Ubuntu 字型套件](https://packages.ubuntu.com/noble/fonts-wqy-zenhei)。

## 2026-10-15 真實驗收

以下 R08-C 為當時已通過的歷史結果。後續 R08-E `254057c` 的 [run 38713819658](https://github.com/Zimkjdv/ProjMemo/actions/runs/38713819658) Windows 473 Python／36 browser／66 Node 成功，但 Linux 新 PDF 測試三項失敗，原因為文泉驛缺少 U+2022。已補實際 glyph 選擇與三個單元案例；當時依使用者要求，修正後 Linux 雲端驗收延至下次，未冒稱已通過。本機載入同版字型的成功不能取代 Linux OS／GitHub Actions 驗收。2026-10-16 實際補驗結果另記於下方，不覆寫這段歷史。

驗收 commit `24d61fc41dd8045c292378a753091f3f34d80c74`，[run 38706234351](https://github.com/Zimkjdv/ProjMemo/actions/runs/38706234351) 最終 conclusion 為 success，兩個 job 皆成功：

| 環境 | Python | Node | 其他 |
| --- | --- | --- | --- |
| Windows baseline | 461 passed、1 skipped | 66 passed | 來源／catalog、真正 batch／reload 通過；唯一 skip 為指定給 Linux 的 CJK 環境檢查。 |
| Linux compatibility and CJK font | 451 passed、11 skipped | 66 passed | CJK 實際載入及 glyph 通過；11 項 skip 明確為 Windows 專用案例。 |

兩邊保留 2 項第三方 httpx／AnyIO 棄用警告。首次 run 38705872022 發現乾淨 checkout 缺少 data 父目錄，並非藉由略過測試修正；已加入目錄建立與回歸斷言後重新推送，以上成功 run 對應的是修正後 commit，不挪用前一個失敗 run 的結果。完整 PDF 視覺／實機剪貼簿不在此驗收內。

## 2026-10-16 Linux／CJK 修正後補驗

對 `main` 手動 Run workflow 並明確勾選 `run_linux`，[run 38839868250](https://github.com/Zimkjdv/ProjMemo/actions/runs/38839868250) 對應 `5d7415671019e83e033105ae02da95d4e91f7455`，最終 success。Windows job `116777254100` 成功後，Linux job `116778604490` 才執行並成功；已核對兩個 job 的實際日誌。

| 環境 | Python | Node | 真實瀏覽器 |
| --- | --- | --- | --- |
| Windows baseline | 476 passed、1 Linux 專用 skipped | 66 passed | Chromium／Firefox／Edge：36 passed |
| Linux compatibility and CJK font | 466 passed、11 Windows 專用 skipped | 66 passed | Chromium／Firefox：24 passed |

兩邊 pip check、來源／catalog 通過，保留 2 項第三方棄用警告。Ubuntu 實際使用 `fonts-wqy-zenhei 0.9.45-8`，必需 CJK 檢查與完整 PDF 回歸均成功，補上先前 glyph 修正後尚未在 Linux OS 跑過的缺口。沒有刪除／降低原失敗測試或新增 skip；工作流與依賴鎖不變。這不是 Linux 正式部署、人工逐頁視覺或 R06 真正 Windows 縮放／系統剪貼簿認證。
