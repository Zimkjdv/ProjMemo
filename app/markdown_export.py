"""Pure Markdown handover renderer; no database or HTTP dependencies."""

from html import escape
import re
import sqlite3
from urllib.parse import quote, urlsplit

from .export_options import ExportOptions
from .options import (status_label, url_type_label, note_category_label, priority_label,
                      checklist_category_label, environment_label, access_environment_label,
                      access_account_category_label)


def markdown_text(value: str, *, multiline: bool = False) -> str:
    """Metadata is literal text, not executable Markdown/HTML; notes are separate."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = escape(text, quote=False)
    text = re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", text)
    if multiline:
        text = re.sub(r"(?m)^([ \t]*)([-+]|\d+[.)])(?=\s)",
                      lambda match: match[1] + match[2][:-1] + "\\" + match[2][-1], text)
    return text if multiline else text.replace("\n", " ")


def markdown_table_cell(value: str) -> str:
    return markdown_text(value or "—")


def markdown_key_cell(value: str) -> str:
    # Backslash escapes inside code spans differ between GFM and Python-Markdown.
    # Only simple identifiers need code styling; complex keys stay literal text.
    return f"`{value}`" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) else markdown_table_cell(value)


def markdown_link(title: str, url: str) -> str:
    try:
        allowed = urlsplit(url).scheme.lower() in {"http", "https"}
    except ValueError:
        allowed = False
    if not allowed:
        return f"{markdown_text(title)} — {markdown_text(url)}"
    destination = escape(quote(url, safe="/:?#@!$&'*+,;=%-._~[]"), quote=False)
    return f"[{markdown_text(title)}]({destination})"


def build_markdown(
    project: sqlite3.Row,
    urls: list[sqlite3.Row],
    notes: list[sqlite3.Row],
    checklist: list[sqlite3.Row],
    environment_variables: list[sqlite3.Row],
    access_accounts: list[dict[str, object]] | None = None,
    *,
    include_secrets: bool = False,
    options: ExportOptions | None = None,
) -> str:
    t = options.label if options else lambda value: value
    colon = ": " if options and options.language == "en" else "："
    selected = options.sections if options else ("description", "urls", "notes", "environment", "accounts", "checklist")
    lines = [
        f"# {markdown_text(project['name'])}",
        "",
        f"- {t('狀態')}{colon}{t(status_label(project['status']))}",
        f"- {t('負責人')}{colon}{markdown_text(project['owner'] or t('未指定'))}",
        f"- {t('標籤')}{colon}{markdown_text(project['tags'] or t('未設定'))}",
        "",
    ]
    if "description" in selected:
        lines.extend(["## " + t("專案描述"), "", markdown_text(project["description"] or t("尚未填寫。"), multiline=True), ""])
    if include_secrets:
        lines.extend(["> ⚠️ " + t("此匯出檔包含實際密碼，請使用安全管道傳送並在交接後刪除暫存副本。"), ""])
    if "urls" in selected:
        lines.extend([
            "## " + t("重要 URL"),
            "",
        ])
        if urls:
            for item in urls:
                lines.append(f"- [{t(url_type_label(item['type']))}] {markdown_link(item['title'], item['url'])}")
                if item["note"]:
                    lines.append(f"  - {t('備註')}{colon}{markdown_text(item['note'])}")
        else:
            lines.append(t("尚未建立 URL。"))
    if "notes" in selected:
        lines.extend(["", "## " + t("Notes & Cautions"), ""])
        if notes:
            for note in notes:
                lines.extend(
                    [
                        f"### {markdown_text(note['title'])}",
                        "",
                        f"- {t('類型')}{colon}{t(note_category_label(note['category']))}",
                        f"- {t('優先級')}{colon}{t(priority_label(note['priority']))}",
                        "",
                        note["content_markdown"],
                        "",
                    ]
                )
        else:
            lines.append(t("尚未建立備註。"))
    if "environment" in selected:
        lines.extend(["## " + t("環境變數說明"), ""])
        if environment_variables:
            lines.extend(["| " + " | ".join(t(label) for label in ("變數", "環境", "說明", "Secret 存放位置/負責人")) + " |", "| --- | --- | --- | --- |"])
            for variable in environment_variables:
                value_description = t("Secret（不匯出值）") if variable["is_secret"] else variable["description"]
                lines.append(
                    f"| {markdown_key_cell(variable['key'])} | "
                    f"{markdown_table_cell(t(environment_label(variable['environment'])))} | "
                    f"{markdown_table_cell(value_description)} | "
                    f"{markdown_table_cell(variable['source_or_owner'])} |"
                )
        else:
            lines.append(t("尚未建立環境變數說明。"))
    if "accounts" in selected:
        lines.extend(["", "## " + t("帳號與存取資料"), ""])
        if access_accounts:
            for account in access_accounts:
                lines.extend([
                    f"### {markdown_text(account['label'])}",
                    "",
                    f"- {t('類型')}{colon}{t(access_account_category_label(str(account['category'])))}",
                    f"- {t('環境')}{colon}{t(access_environment_label(str(account['environment'])))}",
                ])
                if account["endpoint"]:
                    lines.append(f"- {t('端點／登入網址')}{colon}{markdown_text(account['endpoint'])}")
                if account["database_name"]:
                    lines.append(f"- {t('資料庫')}{colon}{markdown_text(account['database_name'])}")
                if account["username"]:
                    lines.append(f"- {t('帳號')}{colon}{markdown_text(account['username'])}")
                if account["role_scope"]:
                    lines.append(f"- {t('權限')}{colon}{markdown_text(account['role_scope'])}")
                if account["purpose"]:
                    lines.append(f"- {t('用途')}{colon}{markdown_text(account['purpose'])}")
                if account["owner"]:
                    lines.append(f"- {t('負責人')}{colon}{markdown_text(account['owner'])}")
                if include_secrets and account.get("secret_value") is not None:
                    secret_text = str(account["secret_value"])
                    fence = "```"
                    while fence in secret_text:
                        fence += "`"
                    lines.extend([f"- {t('密碼（敏感）')}{colon}", "", f"{fence}text", secret_text, fence])
                elif account["has_secret"]:
                    lines.append(f"- {t('密碼')}{colon}{t('已保存於 ProjMemo 保管庫（未匯出）')}")
                elif account["secret_reference"]:
                    lines.append(f"- {t('密碼保管位置')}{colon}{markdown_text(account['secret_reference'])}")
                else:
                    lines.append(f"- {t('密碼')}{colon}{t('未保存')}")
                lines.append("")
        else:
            lines.append(t("尚未建立帳號與存取資料。"))
    lines.append("")
    if "checklist" in selected:
        lines.extend(["## " + t("Handover Checklist"), ""])
        if checklist:
            for item in checklist:
                marker = "x" if item["completed"] else " "
                owner = f"（{t('負責人')}{colon}{markdown_text(item['owner'])}）" if item["owner"] else ""
                lines.append(f"- [{marker}] {markdown_text(item['title'])} {owner}")
                if item["description"]:
                    lines.append(f"  - {markdown_text(item['description'])}")
                if item["note"]:
                    lines.append(f"  - {t('備註')}{colon}{markdown_text(item['note'])}")
        else:
            lines.append(t("尚未建立交接項目。"))
    lines.append("")
    return "\n".join(lines)
