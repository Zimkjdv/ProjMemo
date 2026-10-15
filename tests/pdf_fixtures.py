"""Synthetic PDF coverage: no files, credentials, database or network access."""

from app.project_data import ProjectData

SECRET = "R08-SYNTHETIC-SECRET<&>only"


def pdf_fixture(kind="mixed"):
    project = dict(id=1, name="專案交接 PDF / Export validation", status="maintenance",
                   owner="Fixture team", tags="Python, API", description="繁體中文與 English，保留 <literal> & punctuation。")
    empty = ProjectData(project, [], [], [], [], [])
    if kind == "empty":
        return empty
    url = dict(id=1, type="production", title="正式環境 / Production", url="https://example.invalid/" + "long-path/" * 55,
               note="網址安全範例 & 說明")
    note = dict(id=1, title="Markdown / 部署步驟", category="caution", priority="critical",
                content_markdown="## 操作指南\n\n**重要**、*補充*與 `inline_code`。\n\n- 確認環境\n- 保留備份\n\n> 交接注意事項\n\n"
                + "```python\n" + "\n".join(f"print('CODE-{n:03} 中文 & <tag>')" for n in range(90)) + "\n```\n\n"
                + "| Table ID | 說明 |\n| --- | --- |\n"
                + "\n".join(f"| TableRow-{n:03} | 跨頁資料與說明 {n} |" for n in range(80)))
    environment = dict(id=1, key="DATABASE_CONNECTION", environment="production", is_secret=1,
                       description="Do not export stored values", source_or_owner="External fixture vault")
    account = dict(id=1, label="Synthetic database", category="database", environment="staging",
                   endpoint="host.example.invalid:5432", database_name="fixture_db", username="fixture-user",
                   role_scope="Read only", purpose="PDF testing only", owner="Fixture team",
                   secret_reference="External fixture vault", has_secret=True, secret_value=SECRET)
    checklist = [dict(id=n+1, title=f"Checklist-{n:03}", category="deployment", completed=n % 2,
                      description="確認環境、備份與回復步驟。", owner="Fixture team", note="No real account") for n in range(15)]
    if kind == "long-row":
        note["content_markdown"] = "| Row ID | 說明 |\n| --- | --- |\n| LONGROW-BEGIN | " + "跨頁長內容 review " * 900 + " LONGROW-END |"
    elif kind == "long-title":
        project["name"] = "長專案名稱" * 35
    return ProjectData(project, [url], [note], checklist, [environment], [account])
