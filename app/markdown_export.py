"""Pure Markdown handover renderer; no database or HTTP dependencies."""

import sqlite3

from .options import (status_label, url_type_label, note_category_label, priority_label,
                      checklist_category_label, environment_label, access_environment_label,
                      access_account_category_label)


def markdown_table_cell(value: str) -> str:
    return (value or "—").replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def build_markdown(
    project: sqlite3.Row,
    urls: list[sqlite3.Row],
    notes: list[sqlite3.Row],
    checklist: list[sqlite3.Row],
    environment_variables: list[sqlite3.Row],
    access_accounts: list[dict[str, object]] | None = None,
    *,
    include_secrets: bool = False,
) -> str:
    lines = [
        f"# {project['name']}",
        "",
        f"- 狀態：{status_label(project['status'])}",
        f"- 負責人：{project['owner'] or '未指定'}",
        f"- 標籤：{project['tags'] or '未設定'}",
        "",
        "## 專案描述",
        "",
        project["description"] or "尚未填寫。",
        "",
    ]
    if include_secrets:
        lines.extend(["> ⚠️ 此匯出檔包含實際密碼，請使用安全管道傳送並在交接後刪除暫存副本。", ""])
    lines.extend([
        "## 重要 URL",
        "",
    ])
    if urls:
        for item in urls:
            lines.append(f"- [{url_type_label(item['type'])}] [{item['title']}]({item['url']})")
            if item["note"]:
                lines.append(f"  - 備註：{item['note']}")
    else:
        lines.append("尚未建立 URL。")
    lines.extend(["", "## Notes & Cautions", ""])
    if notes:
        for note in notes:
            lines.extend(
                [
                    f"### {note['title']}",
                    "",
                    f"- 類型：{note_category_label(note['category'])}",
                    f"- 優先級：{priority_label(note['priority'])}",
                    "",
                    note["content_markdown"],
                    "",
                ]
            )
    else:
        lines.append("尚未建立備註。")
    lines.extend(["## 環境變數說明", ""])
    if environment_variables:
        lines.extend(["| 變數 | 環境 | 說明 | Secret 存放位置/負責人 |", "| --- | --- | --- | --- |"])
        for variable in environment_variables:
            value_description = "Secret（不匯出值）" if variable["is_secret"] else variable["description"]
            lines.append(
                f"| `{markdown_table_cell(variable['key'])}` | "
                f"{markdown_table_cell(environment_label(variable['environment']))} | "
                f"{markdown_table_cell(value_description)} | "
                f"{markdown_table_cell(variable['source_or_owner'])} |"
            )
    else:
        lines.append("尚未建立環境變數說明。")
    lines.extend(["## 帳號與存取資料", ""])
    if access_accounts:
        for account in access_accounts:
            lines.extend([
                f"### {account['label']}",
                "",
                f"- 類型：{access_account_category_label(str(account['category']))}",
                f"- 環境：{access_environment_label(str(account['environment']))}",
            ])
            if account["endpoint"]:
                lines.append(f"- 端點／登入網址：{account['endpoint']}")
            if account["database_name"]:
                lines.append(f"- 資料庫：{account['database_name']}")
            if account["username"]:
                lines.append(f"- 帳號：{account['username']}")
            if account["role_scope"]:
                lines.append(f"- 權限：{account['role_scope']}")
            if account["purpose"]:
                lines.append(f"- 用途：{account['purpose']}")
            if account["owner"]:
                lines.append(f"- 負責人：{account['owner']}")
            if include_secrets and account.get("secret_value") is not None:
                secret_text = str(account["secret_value"])
                fence = "```"
                while fence in secret_text:
                    fence += "`"
                lines.extend(["- 密碼（敏感）：", "", f"{fence}text", secret_text, fence])
            elif account["has_secret"]:
                lines.append("- 密碼：已保存於 ProjMemo 保管庫（未匯出）")
            elif account["secret_reference"]:
                lines.append(f"- 密碼保管位置：{account['secret_reference']}")
            else:
                lines.append("- 密碼：未保存")
            lines.append("")
    else:
        lines.append("尚未建立帳號與存取資料。")
    lines.append("")
    lines.extend(["## Handover Checklist", ""])
    if checklist:
        for item in checklist:
            marker = "x" if item["completed"] else " "
            owner = f"（負責人：{item['owner']}）" if item["owner"] else ""
            lines.append(f"- [{marker}] {item['title']} {owner}")
            if item["description"]:
                lines.append(f"  - {item['description']}")
            if item["note"]:
                lines.append(f"  - 備註：{item['note']}")
    else:
        lines.append("尚未建立交接項目。")
    lines.append("")
    return "\n".join(lines)
