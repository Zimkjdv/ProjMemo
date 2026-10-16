# Windows 桌面實機驗收操作

更新日期：2026-10-16。這是可重跑的隔離操作指南，不取代 [ROADMAP.MD](../ROADMAP.MD) 的待驗收項目；設計與原始規劃仍在 [desktop-ui.md](desktop-ui.md)。

## 隔離範例服務

使用已安裝 `requirements-test.txt` 的開發 venv，從專案根目錄執行：

```powershell
python -m tests.desktop_fixture
```

第一行 JSON 回傳實際 `http://127.0.0.1:<port>`、三個範例的 ID 與 `clipboard` 模式。將該網址加上 `/projects/2` 即混合內容頁；1 為空專案、3 為大量內容（250 備註／30 帳號）。三個專案與 `example.invalid` 網域全部是假資料，不含實際密碼，不要開啟範例外部連結。

工具只會新建 `data/r06-desktop-*` 私有目錄；先覆寫 DB 路徑才匯入應用，不接受指定 DB 或 host 的參數。loopback port 0 綁定後持有 socket，不重用正式服務或停止其他程式。服務結束會清除此目錄；以程式呼叫時關閉 stdin（EOF），互動終端可用 Ctrl+C 正常結束。意外中斷留下目錄時，先核對程序已停止，再只清除該輪精確路徑，不刪整個 data。

## R06-B：Windows 系統剪貼簿貼回

正常模式不包裝應用、不注入或替換 Clipboard API，也不讀取使用者原先的剪貼簿。開始後剪貼簿會被範例文字覆蓋；請先完成原本需要貼上的內容。不要以工具的 `clipboard.writeText` 或直接填入預期值代替 Ctrl+V。

1. 在實際 Windows Chrome 開啟混合範例。展開「Fixture note 003」及「新增 Markdown 備註」。
2. 用頁面按鈕複製 URL，親手 Ctrl+V 貼入新增備註的 Markdown 欄位；確認包含完整尾端 query／fragment，而非兩行摘要。
3. 分別複製主機／登入網址、登入帳號及程式碼，依序貼進同一欄位，各段以換行分隔。不要提交表單。
4. 將實際貼回值與 `tests/desktop_fixture.py` 的四個 `COPY_*` 常數逐字比對。程式碼須保留中文、`<tag> &`、四個空白縮排、空行及結尾換行；不只看成功提示或字數。
5. 記錄實際 OS／瀏覽器、語言／檢視、比對結果及方法，清除未存測試草稿後正常結束服務。不讀取或測試任何真實密碼。

2026-10-16 已完成正常模式的真正 Windows Chrome 系統貼回。工具 Ctrl+V 因使用虛擬剪貼簿而失敗，未算通過；改由使用者親手按頁面複製與 Ctrl+V，代理只讀實際貼回文字並逐字比對，沒有直接填入預期值或使用工具剪貼簿。

| 原文 | 字元數 | 實際結果 |
| --- | --- | --- |
| URL | 919 | 隔離 `TEST` 備註的三份原文完整相符，含 query／fragment |
| 主機／登入網址 | 787 | 未儲存 Markdown 欄位中的完整原文相符 |
| 登入帳號 | 721 | 含中文尾端的完整原文相符 |
| 多行程式碼 | 83 | 中文、特殊符號、四空白縮排、空行及結尾換行完整相符 |

後三段實際輸入框共 1597 字元，原文之間僅有換行；在繁中卡片模式完成，其他語言／檢視的共用操作另由回歸及以下故障矩陣檢查。未存貼回文字已清除。請不要儲存程式碼貼回表單：儲存時的正文外層 `.strip()` 會移除尾端換行，無法據此判斷剪貼簿原有的結尾空白。

## 拒絕／不可用的頁面回饋

```powershell
python -m tests.desktop_fixture --clipboard denied
python -m tests.desktop_fixture --clipboard unavailable
```

每次執行仍建立不同的私有 DB／port。這兩種明確選擇的模式只在測試頁 `<head>` 注入固定、頁面範圍的模擬：`writeText` 拋出 `NotAllowedError` 或不存在 Clipboard API。原靜態 JS、應用安全規則與 Chrome 權限都不變，不是停用瀏覽器安全，也不宣稱已重現真正 OS 拒絕權限。

在繁中／英文及卡片／明細中點四類複製按鈕，確認沒有成功回報，顯示對應的「複製失敗，請選取文字後手動複製。」提示，原文仍可選取。Python 的四項 helper 回歸檢查隔離範例、完整渲染程式碼、無密文與明確模擬邊界；既有 Node 測試檢查 Promise／缺 API 與文字完整性。這些自動化不代替上述系統貼回。

2026-10-16 已在實際 Chrome 操作兩種模式 × 繁中／英文 × 卡片／明細 × 四類複製，共 32 組：全部 `failed`，提示符合語言，來源節點原文不變。英文提示為 `Copy failed. Select the text and copy it manually.`；未操作 Chrome 權限或聲稱真實 OS 拒絕權限。語言 cookie 可能在同主機的不同 port 共用，測試完已還原繁中；資料庫／localStorage 的隔離不代表瀏覽器所有設定都按 port 隔離。

## R06：真正縮放

沿用三個隔離範例檢查 1280／1440／1920、兩種語言與卡片／明細。125%／150% 必須由真正 Windows 顯示縮放或桌面瀏覽器縮放設定，記錄實際方法與最後還原方式；viewport、CSS zoom、deviceScaleFactor 或單純除以倍率均不能當成已完成。

目前仍須核對完整原驗收矩陣、字型可讀性、焦點／鍵盤、展開表單與未存草稿，完成後才把 Roadmap 的三條原文移入 Changelog。共享範例工具不表示這些項目已驗收。
