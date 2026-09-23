"""ProjMemo local web application."""

from pathlib import Path
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown import markdown as render_markdown

from .db import db_session, init_db


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_OPTIONS = [
    ("maintenance", "維護中"),
    ("completed", "已結案"),
    ("handover", "移交中"),
]
URL_TYPES = [
    ("production", "正式環境"),
    ("staging", "測試環境"),
    ("git", "Git Repository"),
    ("figma", "Figma"),
    ("api_docs", "API 文件"),
    ("other", "其他"),
]
NOTE_CATEGORIES = [
    ("note", "一般備註"),
    ("caution", "注意事項"),
    ("known_issue", "Known Issue"),
    ("workaround", "Workaround"),
]
PRIORITIES = [("normal", "一般"), ("high", "重要"), ("critical", "關鍵")]
CHECKLIST_CATEGORIES = [
    ("account", "帳號與權限"),
    ("deployment", "部署"),
    ("environment", "環境"),
    ("service", "第三方服務"),
    ("other", "其他"),
]
ENVIRONMENTS = [
    ("local", "Local"),
    ("staging", "Staging"),
    ("production", "Production"),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ProjMemo", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def page_context(request: Request, **values: object) -> dict[str, object]:
    return {
        "request": request,
        "status_options": STATUS_OPTIONS,
        "url_types": URL_TYPES,
        "note_categories": NOTE_CATEGORIES,
        "priorities": PRIORITIES,
        "checklist_categories": CHECKLIST_CATEGORIES,
        "environments": ENVIRONMENTS,
        **values,
    }


def get_project(connection: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    project = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="找不到此專案")
    return project


def project_detail(connection: sqlite3.Connection, project_id: int) -> dict[str, object]:
    project = get_project(connection, project_id)
    return {
        "project": project,
        "urls": connection.execute(
            "SELECT * FROM project_urls WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall(),
        "notes": connection.execute(
            "SELECT * FROM notes WHERE project_id = ? ORDER BY id DESC", (project_id,)
        ).fetchall(),
        "checklist": connection.execute(
            "SELECT * FROM checklist_items WHERE project_id = ? ORDER BY completed, id DESC",
            (project_id,),
        ).fetchall(),
        "environment_variables": connection.execute(
            """
            SELECT * FROM environment_variables
            WHERE project_id = ?
            ORDER BY CASE environment
                WHEN 'local' THEN 1 WHEN 'staging' THEN 2 WHEN 'production' THEN 3 ELSE 4
            END, key COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall(),
    }


def redirect_to_project(project_id: int) -> RedirectResponse:
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


def markdown_filter(value: str) -> str:
    return render_markdown(
        value or "",
        extensions=["fenced_code", "tables", "nl2br"],
    )


templates.env.filters["markdown"] = markdown_filter


@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", status: str = "") -> HTMLResponse:
    query = "SELECT * FROM projects WHERE 1 = 1"
    params: list[str] = []
    if q.strip():
        query += " AND (name LIKE ? OR description LIKE ? OR tags LIKE ?)"
        search = f"%{q.strip()}%"
        params.extend([search, search, search])
    if status in {value for value, _ in STATUS_OPTIONS}:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC, id DESC"
    with db_session() as connection:
        projects = connection.execute(query, params).fetchall()
    return templates.TemplateResponse(
        request,
        "index.html",
        page_context(request, projects=projects, q=q, selected_status=status),
    )


@app.get("/projects/new", response_class=HTMLResponse)
def new_project(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "project_form.html",
        page_context(request, project=None, form_title="建立專案"),
    )


@app.post("/projects/new")
def create_project(
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("maintenance"),
    owner: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="專案名稱不可為空白")
    if status not in {value for value, _ in STATUS_OPTIONS}:
        status = "maintenance"
    with db_session() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects (name, description, status, owner, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), description.strip(), status, owner.strip(), tags.strip()),
        )
        project_id = cursor.lastrowid
    return redirect_to_project(int(project_id))


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def show_project(request: Request, project_id: int) -> HTMLResponse:
    with db_session() as connection:
        values = project_detail(connection, project_id)
    return templates.TemplateResponse(request, "project_detail.html", page_context(request, **values))


@app.get("/projects/{project_id}/edit", response_class=HTMLResponse)
def edit_project(request: Request, project_id: int) -> HTMLResponse:
    with db_session() as connection:
        project = get_project(connection, project_id)
    return templates.TemplateResponse(
        request,
        "project_form.html",
        page_context(request, project=project, form_title="編輯專案"),
    )


@app.post("/projects/{project_id}/edit")
def update_project(
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("maintenance"),
    owner: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="專案名稱不可為空白")
    if status not in {value for value, _ in STATUS_OPTIONS}:
        status = "maintenance"
    with db_session() as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, status = ?, owner = ?, tags = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name.strip(), description.strip(), status, owner.strip(), tags.strip(), project_id),
        )
    return redirect_to_project(project_id)


@app.post("/projects/{project_id}/urls")
def add_url(
    project_id: int,
    type: str = Form("other"),
    title: str = Form(...),
    url: str = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    if type not in {value for value, _ in URL_TYPES}:
        type = "other"
    if not title.strip() or not url.strip():
        raise HTTPException(status_code=400, detail="URL 標題與網址不可為空白")
    if not url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="網址必須以 http:// 或 https:// 開頭")
    with db_session() as connection:
        get_project(connection, project_id)
        connection.execute(
            "INSERT INTO project_urls (project_id, type, title, url, note) VALUES (?, ?, ?, ?, ?)",
            (project_id, type, title.strip(), url.strip(), note.strip()),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/urls/{url_id}/edit")
def update_url(
    url_id: int,
    type: str = Form("other"),
    title: str = Form(...),
    url: str = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    if type not in {value for value, _ in URL_TYPES}:
        type = "other"
    if not title.strip() or not url.strip():
        raise HTTPException(status_code=400, detail="URL 標題與網址不可為空白")
    if not url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="網址必須以 http:// 或 https:// 開頭")
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM project_urls WHERE id = ?", (url_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此 URL")
        project_id = item["project_id"]
        connection.execute(
            """
            UPDATE project_urls SET type = ?, title = ?, url = ?, note = ?
            WHERE id = ?
            """,
            (type, title.strip(), url.strip(), note.strip(), url_id),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/urls/{url_id}/delete")
def delete_url(url_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM project_urls WHERE id = ?", (url_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此 URL")
        project_id = item["project_id"]
        connection.execute("DELETE FROM project_urls WHERE id = ?", (url_id,))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/projects/{project_id}/notes")
def add_note(
    project_id: int,
    category: str = Form("note"),
    title: str = Form(...),
    content_markdown: str = Form(...),
    priority: str = Form("normal"),
) -> RedirectResponse:
    if category not in {value for value, _ in NOTE_CATEGORIES}:
        category = "note"
    if priority not in {value for value, _ in PRIORITIES}:
        priority = "normal"
    if not title.strip() or not content_markdown.strip():
        raise HTTPException(status_code=400, detail="備註標題與內容不可為空白")
    with db_session() as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            INSERT INTO notes (project_id, category, title, content_markdown, priority)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, category, title.strip(), content_markdown.strip(), priority),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/notes/{note_id}/edit")
def update_note(
    note_id: int,
    category: str = Form("note"),
    title: str = Form(...),
    content_markdown: str = Form(...),
    priority: str = Form("normal"),
) -> RedirectResponse:
    if category not in {value for value, _ in NOTE_CATEGORIES}:
        category = "note"
    if priority not in {value for value, _ in PRIORITIES}:
        priority = "normal"
    if not title.strip() or not content_markdown.strip():
        raise HTTPException(status_code=400, detail="備註標題與內容不可為空白")
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此備註")
        project_id = item["project_id"]
        connection.execute(
            """
            UPDATE notes
            SET category = ?, title = ?, content_markdown = ?, priority = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (category, title.strip(), content_markdown.strip(), priority, note_id),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/notes/{note_id}/delete")
def delete_note(note_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此備註")
        project_id = item["project_id"]
        connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/projects/{project_id}/checklist")
def add_checklist_item(
    project_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    description: str = Form(""),
    owner: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    if category not in {value for value, _ in CHECKLIST_CATEGORIES}:
        category = "other"
    if not title.strip():
        raise HTTPException(status_code=400, detail="交接項目不可為空白")
    with db_session() as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            INSERT INTO checklist_items
                (project_id, category, title, description, owner, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, category, title.strip(), description.strip(), owner.strip(), note.strip()),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/checklist/{item_id}/toggle")
def toggle_checklist(item_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id, completed FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此交接項目")
        connection.execute(
            """
            UPDATE checklist_items
            SET completed = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (0 if item["completed"] else 1, item_id),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (item["project_id"],),
        )
        project_id = item["project_id"]
    return redirect_to_project(int(project_id))


@app.post("/checklist/{item_id}/edit")
def update_checklist_item(
    item_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    description: str = Form(""),
    owner: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    if category not in {value for value, _ in CHECKLIST_CATEGORIES}:
        category = "other"
    if not title.strip():
        raise HTTPException(status_code=400, detail="交接項目不可為空白")
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此交接項目")
        project_id = item["project_id"]
        connection.execute(
            """
            UPDATE checklist_items
            SET category = ?, title = ?, description = ?, owner = ?, note = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (category, title.strip(), description.strip(), owner.strip(), note.strip(), item_id),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/checklist/{item_id}/delete")
def delete_checklist_item(item_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此交接項目")
        project_id = item["project_id"]
        connection.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/projects/{project_id}/environment-variables")
def add_environment_variable(
    project_id: int,
    key: str = Form(...),
    environment: str = Form("local"),
    description: str = Form(""),
    source_or_owner: str = Form(""),
    is_secret: bool = Form(False),
) -> RedirectResponse:
    if environment not in {value for value, _ in ENVIRONMENTS}:
        environment = "local"
    if not key.strip():
        raise HTTPException(status_code=400, detail="環境變數名稱不可為空白")
    with db_session() as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            INSERT INTO environment_variables
                (project_id, key, environment, description, source_or_owner, is_secret)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                key.strip(),
                environment,
                description.strip(),
                source_or_owner.strip(),
                int(is_secret),
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/environment-variables/{variable_id}/edit")
def update_environment_variable(
    variable_id: int,
    key: str = Form(...),
    environment: str = Form("local"),
    description: str = Form(""),
    source_or_owner: str = Form(""),
    is_secret: bool = Form(False),
) -> RedirectResponse:
    if environment not in {value for value, _ in ENVIRONMENTS}:
        environment = "local"
    if not key.strip():
        raise HTTPException(status_code=400, detail="環境變數名稱不可為空白")
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM environment_variables WHERE id = ?", (variable_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此環境變數")
        project_id = item["project_id"]
        connection.execute(
            """
            UPDATE environment_variables
            SET key = ?, environment = ?, description = ?, source_or_owner = ?,
                is_secret = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                key.strip(),
                environment,
                description.strip(),
                source_or_owner.strip(),
                int(is_secret),
                variable_id,
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


@app.post("/environment-variables/{variable_id}/delete")
def delete_environment_variable(variable_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM environment_variables WHERE id = ?", (variable_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此環境變數")
        project_id = item["project_id"]
        connection.execute("DELETE FROM environment_variables WHERE id = ?", (variable_id,))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(int(project_id))


def status_label(status: str) -> str:
    return dict(STATUS_OPTIONS).get(status, status)


def url_type_label(url_type: str) -> str:
    return dict(URL_TYPES).get(url_type, url_type)


def note_category_label(category: str) -> str:
    return dict(NOTE_CATEGORIES).get(category, category)


def checklist_category_label(category: str) -> str:
    return dict(CHECKLIST_CATEGORIES).get(category, category)


def priority_label(priority: str) -> str:
    return dict(PRIORITIES).get(priority, priority)


def environment_label(environment: str) -> str:
    return dict(ENVIRONMENTS).get(environment, environment)


def markdown_table_cell(value: str) -> str:
    return (value or "—").replace("\r", " ").replace("\n", " ").replace("|", "\\|")


templates.env.globals.update(
    status_label=status_label,
    url_type_label=url_type_label,
    note_category_label=note_category_label,
    checklist_category_label=checklist_category_label,
    priority_label=priority_label,
    environment_label=environment_label,
)


def build_markdown(
    project: sqlite3.Row,
    urls: list[sqlite3.Row],
    notes: list[sqlite3.Row],
    checklist: list[sqlite3.Row],
    environment_variables: list[sqlite3.Row],
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
        "## 重要 URL",
        "",
    ]
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


@app.get("/projects/{project_id}/export.md")
def export_markdown(project_id: int) -> Response:
    with db_session() as connection:
        values = project_detail(connection, project_id)
    project = values["project"]
    content = build_markdown(
        project,
        values["urls"],
        values["notes"],
        values["checklist"],
        values["environment_variables"],
    )
    filename = f"{project['name']}.md".replace("/", "-").replace("\\", "-")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="projmemo-{project_id}.md"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )
