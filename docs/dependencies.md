# 依賴基線、鎖定與安全更新

## 支援範圍

目前驗證基線是 Windows x64、CPython 3.12（本輪 3.12.10）；SQLite 來自該 Python 發行版，並非 pip 套件。setup 明確使用 `py -3.12`，啟動檢查拒絕其他 minor 版。Node 只供前端測試，不是 runtime。Linux／Docker／其他 Python 版本尚未認證，不能將 Windows 鎖定結果當作跨平台保證。

`requirements.in` 是人工維護的直接 runtime 需求；`requirements.txt` 是含全部間接依賴與 SHA-256 的生成鎖。`requirements-test.in` 加入 pytest／httpx 並受 runtime 鎖約束，生成完整 `requirements-test.txt`。日常 setup 只安裝 runtime；開發者額外執行：

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-test.txt
.\.venv\Scripts\python.exe -m pip check
```

舊 venv 不會自動移除曾裝過的 pytest／httpx；需要純 runtime 時另建乾淨 venv，不要刪除 data。pip 本身由 Python ensurepip 提供，不在應用鎖中；它仍須單獨維護／掃描。雜湊確認下載內容符合鎖定，不保證套件本身安全。

## 明確更新流程

先停止服務、下載備份，保存目前 Git revision 與舊鎖。使用獨立維護 venv（不要把工具混入 runtime）：

```powershell
py -3.12 -m venv data/dependency-tools
.\data\dependency-tools\Scripts\python.exe -m pip install -r requirements-tools.txt
.\data\dependency-tools\Scripts\python.exe -m piptools compile --strip-extras --no-header --no-annotate --no-emit-index-url --no-emit-trusted-host --output-file=data/runtime-pins.txt requirements.in
.\data\dependency-tools\Scripts\python.exe scripts/hash_lock.py data/runtime-pins.txt requirements.txt
.\data\dependency-tools\Scripts\python.exe -m piptools compile --strip-extras --no-header --no-annotate --no-emit-index-url --no-emit-trusted-host --output-file=data/test-pins.txt requirements-test.in
.\data\dependency-tools\Scripts\python.exe scripts/hash_lock.py data/test-pins.txt requirements-test.txt
.\data\dependency-tools\Scripts\python.exe -m pip_audit --require-hashes -r requirements.txt
.\data\dependency-tools\Scripts\python.exe -m pip_audit --require-hashes -r requirements-test.txt
```

只編輯 `.in` 的直接版本；必要時有意識使用 `--upgrade-package NAME` 更新間接依賴，不能任意手改生成雜湊。先重新產生 runtime 再產生 test，審查差異、套件官方變更與公告。`hash_lock.py` 對完整固定閉包取得官方 PyPI 版本 JSON 的發行檔 SHA-256，檢查名稱／版本與格式；全部成功才原子替換鎖，不需下載每個平台的 archive 來算雜湊。pip 安裝時仍驗證實際檔案。不支援 URL／editable／含標記的非平坦輸入。也可使用 pip-tools 原生 `--generate-hashes`，但勿在失敗後把部分結果當作完成。`requirements-tools.txt` 僅釘選維護工具直接版本，不冒充完整工具環境鎖；正式應用及測試閉包才由雜湊鎖完整固定。

在新的隔離 3.12 venv 以 `--require-hashes` 安裝，再執行 `pip check`、完整 Python／Node 回歸、HTTP 契約、保管庫與備份／migration、真實 normal／reload socket 測試。確認後提交 `.in`、兩份鎖與審計紀錄，再停止舊服務執行 setup 更新正式 venv。失敗時切回舊 Git／鎖並重建 venv；不要降版資料庫，資料復原依備份／migration 文件操作。

已安裝環境的日常啟動不連網；首次安裝／更新通常需要網路。要離線重建，先在相同平台用 `pip download --require-hashes -r requirements.txt -d data/wheels` 下載完整 wheelhouse，再 `pip install --no-index --find-links=data/wheels --require-hashes -r requirements.txt`。鎖定不等於已備妥離線套件。

## 安全掃描界線

pip-audit 使用 PyPI 已知公告服務；exit 0 表示該次掃描沒有查到已知漏洞，不是安全保證，連線錯誤或未完整查核不能算通過。不可用 ignore／suppress exit code 將漏洞隱藏。套件名稱／版本會送往服務，不包含 ProjMemo DB／密碼。更新前後摘要保存在本節歷史審計紀錄中；之後升級時應重新掃描。維護工具可定期更新，不在日常啟動時偷偷連網更新。

官方依據：[pip-audit](https://github.com/pypa/pip-audit)、[pip-tools 的分層／雜湊與環境限制](https://pip-tools.pypa.io/en/stable/)、[pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)。

### 2026-10-15 審計紀錄

[可追溯套件／公告摘要](dependency-audit-2026-10-15.json)：原安裝環境中 pytest 8.3.5、python-multipart 0.0.20、Starlette 0.46.2 共 14 個不同公告 ID（服務重複回傳共 28 筆，不當作 28 種漏洞）。其中 [Starlette Windows UNC 問題](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r) 與本機 Windows 靜態檔案場景相關；沒有因個人部署就忽略。

改為 FastAPI 0.135.4／Starlette 1.3.1、python-multipart 0.0.32、pytest 9.0.3；PyPI 含雜湊掃描 runtime 30 個、test 閉包 38 個套件均 exit 0，無已知公告。這不是「保證無漏洞」，也不涵蓋 OS、Python／SQLite 發行版或維護工具。pip bootstrap 由 Python 提供，本機原 venv 為 26.2.1；新 venv 的 ensurepip 版本可能較舊，維護者應另行審查並明確更新 pip，不將它混同為應用依賴掃描結果。

完整回歸保留歷史 HTTP 契約：明確維持上傳欄位 `format: binary`，以及「已送出空白」400／「未送欄位」422 的差別。新版 Starlette 的 httpx 測試介面與 AnyIO 棄用警告保留並說明，未為了消除警告而加入無關 runtime 套件。正式使用前先停止舊服務，再執行 setup 更新；這輪驗證在獨立 venv，不熱更正在使用的正式 venv。
