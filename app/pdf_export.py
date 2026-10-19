"""Create a polished, Traditional Chinese project handover PDF."""

from functools import lru_cache
from html import escape
from io import BytesIO
import os
from pathlib import Path
import re
from typing import Any

from .export_options import ExportOptions
from .options import (
    STATUS_OPTIONS, URL_TYPES, NOTE_CATEGORIES, PRIORITIES, CHECKLIST_CATEGORIES,
    ENVIRONMENTS, ACCESS_ACCOUNT_CATEGORIES, ACCESS_ENVIRONMENTS,
)

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


INK = colors.HexColor("#1D2939")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#E4E7EC")
PRIMARY = colors.HexColor("#3857D6")
PRIMARY_SOFT = colors.HexColor("#EEF2FF")
PALE = colors.HexColor("#F7F8FA")
CONTENT_WIDTH = A4[0] - 36 * mm - 12  # SimpleDocTemplate's two 6pt frame paddings.


class PDFExportError(RuntimeError):
    """Raised when a platform font capable of rendering Chinese is unavailable."""


@lru_cache(maxsize=1)
def _register_cjk_fonts() -> tuple[str, str]:
    configured_font = os.getenv("PROJMEMO_PDF_FONT")
    configured_bold = os.getenv("PROJMEMO_PDF_BOLD_FONT")
    windows_fonts = Path(os.getenv("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        Path(configured_font) if configured_font else None,
        windows_fonts / "msjh.ttc",
        windows_fonts / "msyh.ttc",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/arphic/ukai.ttc"),
    ]
    sample = "專案備註交接清單環境設定"
    regular_font = None
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            font = TTFont("ProjMemoCJK", str(candidate), subfontIndex=0)
            if not all(ord(character) in font.face.charToGlyph for character in sample):
                continue
            pdfmetrics.registerFont(font)
            regular_font = font
            break
        except Exception:
            continue

    if regular_font is None:
        raise PDFExportError(
            "找不到可用的繁體中文字型。請安裝 Microsoft JhengHei 或 Noto Sans CJK， "
            "也可以用 PROJMEMO_PDF_FONT 指定 .ttf/.ttc 字型檔。"
        )

    bold_candidates = [
        Path(configured_bold) if configured_bold else None,
        windows_fonts / "msjhbd.ttc",
        windows_fonts / "msyhbd.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    ]
    bold_font = None
    for candidate in bold_candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            font = TTFont("ProjMemoCJKBold", str(candidate), subfontIndex=0)
            if all(ord(character) in font.face.charToGlyph for character in sample):
                pdfmetrics.registerFont(font)
                bold_font = font
                break
        except Exception:
            continue

    bold_name = bold_font.fontName if bold_font else regular_font.fontName
    registerFontFamily(
        "ProjMemoCJK",
        normal=regular_font.fontName,
        bold=bold_name,
        italic=regular_font.fontName,
        boldItalic=bold_name,
    )
    return regular_font.fontName, bold_name


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "body": ParagraphStyle(
            "ProjMemoBody", parent=base, fontName=font_name, fontSize=9.2,
            leading=14, textColor=INK, spaceAfter=4, wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "ProjMemoSmall", parent=base, fontName=font_name, fontSize=8,
            leading=11.5, textColor=MUTED, wordWrap="CJK",
        ),
        "title": ParagraphStyle(
            "ProjMemoTitle", parent=base, fontName=font_name, fontSize=23,
            leading=29, textColor=INK, spaceAfter=5, wordWrap="CJK",
        ),
        "subtitle": ParagraphStyle(
            "ProjMemoSubtitle", parent=base, fontName=font_name, fontSize=9.5,
            leading=14, textColor=MUTED, spaceAfter=10, wordWrap="CJK",
        ),
        "section": ParagraphStyle(
            "ProjMemoSection", parent=base, fontName=font_name, fontSize=14,
            leading=19, textColor=INK, spaceBefore=12, spaceAfter=8, keepWithNext=True,
        ),
        "note_title": ParagraphStyle(
            "ProjMemoNoteTitle", parent=base, fontName=font_name, fontSize=10.5,
            leading=15, textColor=INK, spaceBefore=7, spaceAfter=3, keepWithNext=True,
            wordWrap="CJK",
        ),
        "markdown_h2": ParagraphStyle(
            "ProjMemoMarkdownH2", parent=base, fontName=font_name, fontSize=11.5,
            leading=15, textColor=INK, spaceBefore=6, spaceAfter=4, keepWithNext=True,
            wordWrap="CJK",
        ),
        "markdown_h3": ParagraphStyle(
            "ProjMemoMarkdownH3", parent=base, fontName=font_name, fontSize=10,
            leading=13, textColor=INK, spaceBefore=4, spaceAfter=3, keepWithNext=True,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "ProjMemoCode", parent=base, fontName=font_name, fontSize=7.5,
            leading=10, textColor=INK, backColor=PALE, borderColor=LINE,
            borderWidth=.4, borderPadding=6, leftIndent=4, rightIndent=4,
            spaceBefore=3, spaceAfter=7, wordWrap="CJK",
        ),
        "list": ParagraphStyle(
            "ProjMemoList", parent=base, fontName=font_name, fontSize=9,
            bulletFontName=font_name, bulletFontSize=9,
            leading=13.5, textColor=INK, leftIndent=13, firstLineIndent=-10,
            spaceAfter=2, wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "ProjMemoTable", parent=base, fontName=font_name, fontSize=8.1,
            leading=11, textColor=INK, wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "ProjMemoTableHeader", parent=base, fontName=font_name, fontSize=8,
            leading=10.5, textColor=colors.white, wordWrap="CJK",
        ),
        "metadata_label": ParagraphStyle(
            "ProjMemoMetadataLabel", parent=base, fontName=font_name, fontSize=8,
            leading=11, textColor=MUTED,
        ),
        "metadata_value": ParagraphStyle(
            "ProjMemoMetadataValue", parent=base, fontName=font_name, fontSize=8.5,
            leading=12, textColor=INK, wordWrap="CJK",
        ),
        "center": ParagraphStyle(
            "ProjMemoCenter", parent=base, fontName=font_name, fontSize=8,
            leading=11, textColor=MUTED, alignment=TA_CENTER,
        ),
    }


def _safe_paragraph_text(value: str) -> str:
    """Convert a small, safe Markdown inline subset to ReportLab paragraph markup."""
    pattern = re.compile(
        r"(`[^`]+`|\*\*.+?\*\*|(?<!\*)\*[^*]+\*(?!\*)|"
        r"\[[^\]]+\]\(https?://[^)]+\))"
    )
    output: list[str] = []
    cursor = 0
    for match in pattern.finditer(value):
        output.append(escape(value[cursor:match.start()], quote=False).replace("\n", "<br/>"))
        token = match.group(0)
        if token.startswith("`"):
            output.append(f"<font name=\"ProjMemoCJK\">{escape(token[1:-1], quote=False)}</font>")
        elif token.startswith("**"):
            output.append(f"<b>{escape(token[2:-2], quote=False)}</b>")
        elif token.startswith("*"):
            output.append(f"<i>{escape(token[1:-1], quote=False)}</i>")
        else:
            link_match = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)]+)\)", token)
            if link_match:
                label, url = link_match.groups()
                output.append(
                    f'<link href="{escape(url, quote=True)}" color="#3857D6">'
                    f"{escape(label, quote=False)}</link>"
                )
            else:
                output.append(escape(token, quote=False))
        cursor = match.end()
    output.append(escape(value[cursor:], quote=False).replace("\n", "<br/>"))
    return "".join(output) or "&#160;"


def _table_cells(line: str) -> list[str]:
    content = line.strip().strip("|")
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", content)]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _list_bullet(font_name: str) -> str:
    """Some CJK fonts (including WQY) lack U+2022: never emit a .notdef bullet."""
    glyphs = getattr(pdfmetrics.getFont(font_name).face, "charToGlyph", {})
    return next((char for char in ("•", "●", "-") if glyphs.get(ord(char), 0)), "-")


def _markdown_flowables(content: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    lines = (content or "").splitlines()
    flowables: list[Any] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code_lines.append(lines[index])
                index += 1
            index += 1 if index < len(lines) else 0
            code = "\n".join(code_lines) or " "
            flowables.append(
            Preformatted(code, styles["code"], maxLineLength=60)
            )
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped)
        if heading:
            style = styles["markdown_h2"] if len(heading.group(1)) <= 2 else styles["markdown_h3"]
            flowables.append(Paragraph(_safe_paragraph_text(heading.group(2)), style))
            index += 1
            continue

        if "|" in stripped and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            table_lines = [line]
            index += 1
            index += 1  # Markdown table alignment row.
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            rows = [
                [Paragraph(_safe_paragraph_text(cell), styles["table_header"] if row_index == 0 else styles["table"])
                 for cell in _table_cells(row)]
                for row_index, row in enumerate(table_lines)
            ]
            column_count = max((len(row) for row in rows), default=1)
            for row in rows:
                row.extend([Paragraph("&#160;", styles["table"])] * (column_count - len(row)))
            table = LongTable(rows, colWidths=[CONTENT_WIDTH / column_count] * column_count,
                              repeatRows=1, splitInRow=1, hAlign="LEFT")
            table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("GRID", (0, 0), (-1, -1), .35, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ])
            )
            flowables.extend([table, Spacer(1, 5)])
            continue

        if re.fullmatch(r"([-*_])\1{2,}", stripped):
            flowables.append(Spacer(1, 5))
            index += 1
            continue

        list_match = re.match(r"^(\s*)([-*+] |\d+\. )(.*)$", line)
        if list_match:
            while index < len(lines):
                list_match = re.match(r"^(\s*)([-*+] |\d+\. )(.*)$", lines[index])
                if not list_match:
                    break
                indent = min(len(list_match.group(1)) // 2, 4)
                bullet = (_list_bullet(styles["list"].fontName) if list_match.group(2).strip() in {"-", "*", "+"}
                          else list_match.group(2).strip())
                style = ParagraphStyle(
                    f"ProjMemoList{index}", parent=styles["list"],
                    leftIndent=13 + indent * 10, firstLineIndent=-10,
                )
                flowables.append(Paragraph(_safe_paragraph_text(list_match.group(3)), style, bulletText=bullet))
                index += 1
            continue

        if stripped.startswith("> "):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip()[1:].lstrip())
                index += 1
            quote_style = ParagraphStyle(
                f"ProjMemoQuote{index}", parent=styles["body"],
                leftIndent=9, borderColor=LINE, borderWidth=0,
                textColor=MUTED, italic=True,
            )
            flowables.append(Paragraph(_safe_paragraph_text(" ".join(quote_lines)), quote_style))
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if (
                not next_stripped
                or next_stripped.startswith(("```", "~~~", "#", "> "))
                or re.match(r"^(\s*)([-*+] |\d+\. )", next_line)
                or ("|" in next_stripped and index + 1 < len(lines) and _is_table_separator(lines[index + 1]))
                or re.fullmatch(r"([-*_])\1{2,}", next_stripped)
            ):
                break
            paragraph_lines.append(next_stripped)
            index += 1
        flowables.append(Paragraph(_safe_paragraph_text("\n".join(paragraph_lines)), styles["body"]))
    return flowables


def _header_footer(canvas: Any, document: Any, project_name: str, font_name: str,
                   footer: str = "Project handover notes") -> None:
    canvas.saveState()
    page_width, page_height = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(.5)
    canvas.line(18 * mm, page_height - 14 * mm, page_width - 18 * mm, page_height - 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont(font_name, 7.5)
    header = f"ProjMemo  /  {project_name}".replace("\n", " ").replace("\r", " ")
    maximum = page_width - 36 * mm
    if pdfmetrics.stringWidth(header, font_name, 7.5) > maximum:
        while header and pdfmetrics.stringWidth(header + "...", font_name, 7.5) > maximum:
            header = header[:-1]
        header += "..."  # The full project title remains in the body and PDF metadata.
    canvas.drawString(18 * mm, page_height - 11 * mm, header)
    canvas.line(18 * mm, 15 * mm, page_width - 18 * mm, 15 * mm)
    canvas.drawString(18 * mm, 10 * mm, footer)
    canvas.drawRightString(page_width - 18 * mm, 10 * mm, f"{document.page}")
    canvas.restoreState()


def _section_heading(title: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [Paragraph(escape(title), styles["section"])]


def _make_table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
    if widths:
        widths = [width * CONTENT_WIDTH / sum(widths) for width in widths]
    table = LongTable(rows, colWidths=widths, repeatRows=1, splitInRow=1, hAlign="LEFT")
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("GRID", (0, 0), (-1, -1), .35, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ])
    )
    return table


def generate_project_pdf(
    project: Any,
    urls: list[Any],
    notes: list[Any],
    checklist: list[Any],
    environment_variables: list[Any],
    access_accounts: list[Any] | None = None,
    *,
    include_secrets: bool = False,
    options: ExportOptions | None = None,
) -> bytes:
    """Return the project's current handover contents as an A4 PDF."""
    t = options.label if options else lambda value: value
    colon = ": " if options and options.language == "en" else "："
    selected = options.sections if options else ("description", "urls", "notes", "environment", "accounts", "checklist")
    regular_font, _ = _register_cjk_fonts()
    styles = _styles(regular_font)
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=21 * mm,
        bottomMargin=20 * mm,
        title=f"{project['name']} - ProjMemo",
        author="ProjMemo",
        subject="Project handover notes and checklist",
    )
    story: list[Any] = [
        Paragraph(escape(project["name"]), styles["title"]),
        Paragraph(t("Project overview and handover reference"), styles["subtitle"]),
    ]

    status_text = dict(STATUS_OPTIONS).get(
        project["status"], project["status"]
    )
    metadata_rows = [
        [Paragraph(t("狀態"), styles["metadata_label"]), Paragraph(escape(t(status_text)), styles["metadata_value"])],
        [Paragraph(t("負責人"), styles["metadata_label"]), Paragraph(escape(project["owner"] or t("未指定")), styles["metadata_value"])],
        [Paragraph(t("標籤"), styles["metadata_label"]), Paragraph(escape(project["tags"] or t("未設定")), styles["metadata_value"])],
    ]
    metadata = LongTable(metadata_rows, colWidths=[CONTENT_WIDTH * 28 / 173, CONTENT_WIDTH * 145 / 173],
                         splitInRow=1, hAlign="LEFT")
    metadata.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE),
        ("BOX", (0, 0), (-1, -1), .4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([metadata, Spacer(1, 7)])

    if include_secrets and "accounts" not in selected:
        story.append(Paragraph(t("【敏感資料】此 PDF 包含實際密碼，請使用安全管道傳送並在交接後刪除暫存副本。"), styles["small"]))

    if "description" in selected:
        story.extend(_section_heading(t("專案描述"), styles))
        description = project["description"] or t("尚未填寫。")
        story.extend(_markdown_flowables(description, styles))

    if "urls" in selected:
        story.extend(_section_heading(t("重要 URL"), styles))
        if urls:
            rows = [[Paragraph(t(label), styles["table_header"]) for label in (t("類型"), t("名稱與網址"), t("備註"))]]
            for item in urls:
                safe_url = escape(item["url"], quote=True)
                url_paragraph = Paragraph(
                    f'<b>{escape(item["title"])}</b><br/><link href="{safe_url}" color="#3857D6">{escape(item["url"])}</link>',
                    styles["table"],
                )
                rows.append([
                    Paragraph(escape(t(dict(URL_TYPES).get(item["type"], item["type"]))), styles["table"]),
                    url_paragraph,
                    Paragraph(escape(item["note"] or "—"), styles["table"]),
                ])
            story.append(_make_table(rows, [30 * mm, 88 * mm, 55 * mm]))
        else:
            story.append(Paragraph(t("尚未建立重要 URL。"), styles["small"]))

    if "notes" in selected:
        story.extend(_section_heading(t("備註與注意事項"), styles))
        if notes:
            for note in notes:
                note_intro = Paragraph(
                    f"<b>{escape(note['title'])}</b>  "
                    f"<font color=\"#667085\">{escape(t(dict(NOTE_CATEGORIES).get(note['category'], note['category'])))}"
                    f" · {escape(t(dict(PRIORITIES).get(note['priority'], note['priority'])))}</font>",
                    styles["note_title"],
                )
                story.append(note_intro)  # KeepWithNext also links to the first content block.
                story.extend(_markdown_flowables(note["content_markdown"], styles))
        else:
            story.append(Paragraph(t("尚未建立備註。"), styles["small"]))

    if "environment" in selected:
        story.extend(_section_heading(t("環境變數說明"), styles))
        if environment_variables:
            rows = [[Paragraph(label, styles["table_header"]) for label in (t("變數"), t("環境"), t("用途與安全說明"), t("存放位置／負責人"))]]
            for variable in environment_variables:
                description_text = t("Secret（不匯出值）") if variable["is_secret"] else (variable["description"] or "—")
                rows.append([
                    Paragraph(f"<font name=\"ProjMemoCJK\"><b>{escape(variable['key'])}</b></font>", styles["table"]),
                    Paragraph(escape(t(dict(ENVIRONMENTS).get(variable["environment"], variable["environment"]))), styles["table"]),
                    Paragraph(escape(description_text), styles["table"]),
                    Paragraph(escape(variable["source_or_owner"] or "—"), styles["table"]),
                ])
            story.append(_make_table(rows, [38 * mm, 26 * mm, 58 * mm, 51 * mm]))
        else:
            story.append(Paragraph(t("尚未建立環境變數說明。"), styles["small"]))

    if "accounts" in selected:
        story.extend(_section_heading(t("帳號與存取資料"), styles))
        if include_secrets:
            story.append(Paragraph(
                t("【敏感資料】此 PDF 包含實際密碼，請使用安全管道傳送並在交接後刪除暫存副本。"),
                styles["small"],
            ))
        if access_accounts:
            rows = [[Paragraph(label, styles["table_header"]) for label in (t("帳號／類型"), t("環境／端點／用途"), t("使用者／權限／密碼"))]]
            category_labels = dict(ACCESS_ACCOUNT_CATEGORIES)
            access_environment_labels = dict(ACCESS_ENVIRONMENTS)
            for account in access_accounts:
                identity = (
                    f"<b>{escape(str(account['label']))}</b><br/>"
                    f"{escape(t(category_labels.get(str(account['category']), str(account['category']))))}"
                )
                endpoint_lines = [
                    escape(t(access_environment_labels.get(str(account["environment"]), str(account["environment"]))))
                ]
                if account["endpoint"]:
                    endpoint_lines.append(escape(str(account["endpoint"])))
                if account["database_name"]:
                    endpoint_lines.append(f"{t('資料庫')}{colon}{escape(str(account['database_name']))}")
                if account["purpose"]:
                    endpoint_lines.append(f"{t('用途')}{colon}{escape(str(account['purpose']))}")
                identity_lines = []
                if account["username"]:
                    identity_lines.append(f"{t('帳號')}{colon}{escape(str(account['username']))}")
                if account["role_scope"]:
                    identity_lines.append(f"{t('權限')}{colon}{escape(str(account['role_scope']))}")
                if account["owner"]:
                    identity_lines.append(f"{t('負責人')}{colon}{escape(str(account['owner']))}")
                if include_secrets and account.get("secret_value") is not None:
                    # Paragraph normally collapses whitespace, which would change a password.
                    # NBSP preserves visible spaces; Markdown remains the lossless text format.
                    secret_text = escape(str(account["secret_value"])).replace(" ", "&#160;").replace("\n", "<br/>")
                    identity_lines.append(f"{t('密碼')}{colon}{secret_text}")
                elif account["has_secret"]:
                    identity_lines.append(f"{t('密碼')}{colon}{t('已保存於 ProjMemo 保管庫（未匯出）')}")
                elif account["secret_reference"]:
                    identity_lines.append(f"{t('密碼保管位置')}{colon}{escape(str(account['secret_reference']))}")
                else:
                    identity_lines.append(f"{t('密碼')}{colon}{t('未保存')}")
                rows.append([
                    Paragraph(identity, styles["table"]),
                    Paragraph("<br/>".join(endpoint_lines) or "—", styles["table"]),
                    Paragraph("<br/>".join(identity_lines) or "—", styles["table"]),
                ])
            story.append(_make_table(rows, [42 * mm, 64 * mm, 67 * mm]))
        else:
            story.append(Paragraph(t("尚未建立帳號與存取資料。"), styles["small"]))

    if "checklist" in selected:
        story.extend(_section_heading(t("交接清單"), styles))
        if checklist:
            rows = [[Paragraph(label, styles["table_header"]) for label in (t("狀態"), t("類型"), t("項目與說明"), t("負責人"))]]
            for item in checklist:
                item_details = f"<b>{escape(item['title'])}</b>"
                if item["description"]:
                    item_details += f"<br/>{escape(item['description']).replace(chr(10), '<br/>')}"
                if item["note"]:
                    item_details += f"<br/><font color=\"#667085\">{t('備註')}{colon}{escape(item['note'])}</font>"
                rows.append([
                    Paragraph(t("已完成") if item["completed"] else t("待處理"), styles["table"]),
                    Paragraph(escape(t(dict(CHECKLIST_CATEGORIES).get(item["category"], item["category"]))), styles["table"]),
                    Paragraph(item_details, styles["table"]),
                    Paragraph(escape(item["owner"] or "—"), styles["table"]),
                ])
            widths = [25 * mm, 31 * mm, 83 * mm, 34 * mm] if options and options.language == "en" else [20 * mm, 31 * mm, 88 * mm, 34 * mm]
            story.append(_make_table(rows, widths))
        else:
            story.append(Paragraph(t("尚未建立交接項目。"), styles["small"]))

    def page_painter(canvas: Any, doc: Any) -> None:
        _header_footer(canvas, doc, project["name"], regular_font, t("Project handover notes"))

    document.build(story, onFirstPage=page_painter, onLaterPages=page_painter)
    return output.getvalue()
