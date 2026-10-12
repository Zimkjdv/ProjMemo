"""ProjMemo local web application."""

from pathlib import Path
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from math import ceil
from urllib.parse import quote, unquote, urlencode, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown import markdown as render_markdown
import nh3
from starlette.background import BackgroundTask

from .backup import (
    BackupRestoreError,
    BackupValidationError,
    create_temporary_backup,
    is_recovery_backup_filename,
    recovery_directory,
    restore_database,
    save_uploaded_backup,
)
from .db import database_path, db_session, init_db
from .i18n import LANGUAGE_COOKIE, LANGUAGES, get_language, translate_error, translator
from .pdf_export import PDFExportError, generate_project_pdf
from .vault import (
    InvalidMasterPassword,
    UnlockAttemptLimiter,
    VaultAlreadyInitialized,
    VaultError,
    VaultNotInitialized,
    VaultRateLimited,
    VaultSessions,
    create_vault,
    decrypt_secret,
    encrypt_secret,
    unlock_vault,
    validate_master_password,
)


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
ACCESS_ACCOUNT_CATEGORIES = [
    ("database", "資料庫帳號"),
    ("website", "網站／測試帳號"),
    ("server", "主機／SSH"),
    ("cloud", "雲端／IAM"),
    ("service", "第三方服務"),
    ("other", "其他"),
]
ACCESS_ENVIRONMENTS = [
    ("local", "Local"),
    ("development", "開發"),
    ("test", "測試"),
    ("staging", "Staging"),
    ("production", "Production"),
    ("other", "其他"),
]
VAULT_COOKIE_NAME = "projmemo_vault"
vault_sessions = VaultSessions()
unlock_attempt_limiter = UnlockAttemptLimiter()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ProjMemo", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.exception_handler(HTTPException)
async def localized_http_error(request: Request, error: HTTPException) -> JSONResponse:
    detail = (
        translate_error(error.detail, get_language(request))
        if isinstance(error.detail, str) else error.detail
    )
    return JSONResponse({"detail": detail}, status_code=error.status_code, headers=error.headers)


@app.post("/settings/language")
def change_language(
    request: Request,
    language: str = Form(...),
    return_to: str = Form("/"),
) -> RedirectResponse:
    if language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="不支援的介面語言")
    try:
        destination = urlsplit(return_to)
    except ValueError:
        return_to = "/"
        destination = urlsplit(return_to)
    decoded_path = unquote(destination.path)
    if (
        not return_to.startswith("/")
        or destination.scheme
        or destination.netloc
        or unquote(return_to).startswith("//")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(ord(character) < 32 for character in unquote(return_to))
    ):
        return_to = "/"
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie(
        LANGUAGE_COOKIE, language, max_age=365 * 24 * 60 * 60,
        httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/",
    )
    return response


def page_context(request: Request, **values: object) -> dict[str, object]:
    language = get_language(request)
    t = translator(request)
    option_groups = {
        "status_options": (STATUS_OPTIONS, "status_label"),
        "url_types": (URL_TYPES, "url_type_label"),
        "note_categories": (NOTE_CATEGORIES, "note_category_label"),
        "priorities": (PRIORITIES, "priority_label"),
        "checklist_categories": (CHECKLIST_CATEGORIES, "checklist_category_label"),
        "environments": (ENVIRONMENTS, "environment_label"),
        "access_account_categories": (ACCESS_ACCOUNT_CATEGORIES, "access_account_category_label"),
        "access_environments": (ACCESS_ENVIRONMENTS, "access_environment_label"),
    }
    context = {
        "request": request,
        "language": language,
        "t": t,
        "return_to": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        **values,
    }
    for name, (options, label_function) in option_groups.items():
        localized = [(value, t(label)) for value, label in options]
        context[name] = localized
        labels = dict(localized)
        context[label_function] = lambda value, labels=labels: labels.get(value, value)
    if "form_title" in values:
        context["form_title"] = t(str(values["form_title"]))
    if "error" in values:
        context["error"] = translate_error(str(values["error"]), language)
    return context


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
        "access_accounts": [dict(row) for row in connection.execute(
            """
            SELECT id, project_id, label, category, environment, endpoint,
                   database_name, username, role_scope, purpose, owner,
                   secret_reference, secret_ciphertext IS NOT NULL AS has_secret,
                   created_at, updated_at
            FROM access_accounts
            WHERE project_id = ?
            ORDER BY CASE environment
                WHEN 'production' THEN 1 WHEN 'staging' THEN 2 ELSE 3
            END, label COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall()],
    }


def redirect_to_project(project_id: int) -> RedirectResponse:
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


def current_vault_key(request: Request) -> bytes | None:
    return vault_sessions.get_key(request.cookies.get(VAULT_COOKIE_NAME))


def require_vault_key(request: Request) -> bytes:
    key = current_vault_key(request)
    if key is None:
        raise HTTPException(status_code=423, detail="保管庫已鎖定，請先解鎖")
    return key


def vault_page(
    request: Request,
    *,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    with db_session() as connection:
        configured = connection.execute(
            "SELECT 1 FROM vault_config WHERE id = 1"
        ).fetchone() is not None
        settings = connection.execute(
            "SELECT allow_secret_export FROM app_settings WHERE id = 1"
        ).fetchone()
    response = templates.TemplateResponse(
        request,
        "vault.html",
        page_context(
            request,
            vault_configured=configured,
            vault_unlocked=current_vault_key(request) is not None,
            allow_secret_export=bool(settings["allow_secret_export"]) if settings else False,
            error=error,
        ),
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def vault_session_response(request: Request, key: bytes) -> RedirectResponse:
    token = vault_sessions.issue(key)
    response = RedirectResponse(url="/settings/vault", status_code=303)
    response.set_cookie(
        VAULT_COOKIE_NAME,
        token,
        max_age=15 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


MARKDOWN_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "strong", "table", "tbody",
    "td", "th", "thead", "tr", "ul",
}
MARKDOWN_SANITIZER = nh3.Cleaner(
    tags=MARKDOWN_ALLOWED_TAGS,
    attributes={"a": {"href", "title"}, "td": {"align"}, "th": {"align"}},
    url_schemes={"http", "https", "mailto"},
    strip_comments=True,
)


def markdown_filter(value: str) -> str:
    rendered_html = render_markdown(
        value or "",
        extensions=["fenced_code", "tables", "nl2br"],
    )
    return MARKDOWN_SANITIZER.clean(rendered_html)


templates.env.filters["markdown"] = markdown_filter


def _backup_page(
    request: Request,
    *,
    restored: bool = False,
    error: str = "",
    recovery_filename: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    try:
        with db_session() as connection:
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    except sqlite3.Error:
        project_count = None

    backup_directory = recovery_directory(database_path())
    recovery_backups = []
    try:
        backup_paths = sorted(
            backup_directory.glob("projmemo-pre-restore-*.sqlite3"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:10]
        for path in backup_paths:
            stats = path.stat()
            recovery_backups.append(
                {
                    "filename": path.name,
                    "created_at": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "size_mb": max(stats.st_size / (1024 * 1024), 0.01),
                }
            )
    except OSError:
        recovery_backups = []

    if not is_recovery_backup_filename(recovery_filename):
        recovery_filename = ""
    elif not (backup_directory / recovery_filename).is_file():
        recovery_filename = ""

    return templates.TemplateResponse(
        request,
        "backup.html",
        page_context(
            request,
            project_count=project_count,
            restored=restored,
            error=error,
            recovery_filename=recovery_filename,
            recovery_backups=recovery_backups,
        ),
        status_code=status_code,
    )


def _remove_temporary_backup(path: Path) -> None:
    path.unlink(missing_ok=True)


@app.get("/settings/backup", response_class=HTMLResponse)
def backup_settings(
    request: Request,
    restored: bool = False,
    recovery: str = "",
) -> HTMLResponse:
    return _backup_page(request, restored=restored, recovery_filename=recovery)


@app.get("/settings/vault", response_class=HTMLResponse)
def credential_vault_settings(request: Request, error: str = "") -> HTMLResponse:
    return vault_page(request, error=error)


@app.post("/settings/vault/setup")
def setup_credential_vault(
    request: Request,
    master_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    if master_password != confirm_password:
        return vault_page(request, error="兩次輸入的主密碼不一致", status_code=400)
    try:
        with db_session() as connection:
            key = create_vault(connection, master_password)
    except VaultAlreadyInitialized:
        return vault_page(request, error="保管庫已設定，請直接解鎖", status_code=409)
    except VaultError as error:
        return vault_page(request, error=str(error), status_code=400)
    unlock_attempt_limiter.record_success()
    return vault_session_response(request, key)


@app.post("/settings/vault/unlock")
def unlock_credential_vault(
    request: Request,
    master_password: str = Form(...),
) -> Response:
    try:
        unlock_attempt_limiter.check_allowed()
        with db_session() as connection:
            key = unlock_vault(connection, master_password)
    except InvalidMasterPassword:
        unlock_attempt_limiter.record_failure()
        return vault_page(request, error="主密碼錯誤，請確認後再試", status_code=401)
    except VaultRateLimited as error:
        return vault_page(request, error=str(error), status_code=429)
    except VaultNotInitialized:
        return vault_page(request, error="尚未設定保管庫", status_code=409)
    unlock_attempt_limiter.record_success()
    return vault_session_response(request, key)


@app.post("/settings/vault/lock")
def lock_credential_vault(request: Request) -> RedirectResponse:
    vault_sessions.revoke(request.cookies.get(VAULT_COOKIE_NAME))
    response = RedirectResponse(url="/settings/vault", status_code=303)
    response.delete_cookie(VAULT_COOKIE_NAME, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/settings/vault/export-policy")
def update_vault_export_policy(
    request: Request,
    allow_secret_export: bool = Form(False),
) -> Response:
    if allow_secret_export and current_vault_key(request) is None:
        return vault_page(request, error="請先解鎖保管庫，再開啟含密碼匯出", status_code=423)
    with db_session() as connection:
        configured = connection.execute(
            "SELECT 1 FROM vault_config WHERE id = 1"
        ).fetchone() is not None
        if allow_secret_export and not configured:
            return vault_page(request, error="請先設定保管庫，再開啟含密碼匯出", status_code=400)
        connection.execute(
            "UPDATE app_settings SET allow_secret_export = ? WHERE id = 1",
            (int(allow_secret_export),),
        )
    return RedirectResponse(url="/settings/vault", status_code=303)


@app.get("/settings/backup/download")
def download_database_backup() -> FileResponse:
    backup_path = create_temporary_backup(database_path())
    filename = f"projmemo-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=filename,
        background=BackgroundTask(_remove_temporary_backup, backup_path),
    )


@app.post("/settings/backup/restore")
def restore_database_backup(
    request: Request,
    backup_file: UploadFile = File(...),
) -> Response:
    uploaded_path: Path | None = None
    try:
        uploaded_path = save_uploaded_backup(backup_file.file, database_path().parent)
        recovery_path = restore_database(uploaded_path, database_path())
        vault_sessions.clear()
        init_db()
    except BackupValidationError as error:
        return _backup_page(request, error=str(error), status_code=400)
    except BackupRestoreError as error:
        return _backup_page(
            request,
            error=str(error),
            recovery_filename=error.recovery_filename,
            status_code=500,
        )
    except (OSError, sqlite3.Error):
        return _backup_page(
            request,
            error="還原作業失敗，資料未完成替換。請確認磁碟空間與檔案權限。",
            status_code=500,
        )
    finally:
        if uploaded_path is not None:
            uploaded_path.unlink(missing_ok=True)
        backup_file.file.close()

    return RedirectResponse(
        url=f"/settings/backup?restored=1&recovery={quote(recovery_path.name)}",
        status_code=303,
    )


@app.get("/settings/backup/files/{filename}")
def download_recovery_backup(filename: str) -> FileResponse:
    if not is_recovery_backup_filename(filename):
        raise HTTPException(status_code=404, detail="找不到此備份檔")
    backup_path = recovery_directory(database_path()) / filename
    resolved_directory = recovery_directory(database_path()).resolve()
    try:
        if backup_path.is_symlink() or backup_path.resolve().parent != resolved_directory:
            raise HTTPException(status_code=404, detail="找不到此備份檔")
    except OSError as error:
        raise HTTPException(status_code=404, detail="找不到此備份檔") from error
    if not backup_path.is_file():
        raise HTTPException(status_code=404, detail="找不到此備份檔")
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=filename,
    )


def project_list_url(
    q: str,
    status: str,
    view_mode: str,
    page_size: int,
    page: int,
) -> str:
    params = {
        "view": view_mode,
        "page_size": page_size,
        "page": page,
    }
    if q:
        params["q"] = q
    if status:
        params["status"] = status
    return f"/?{urlencode(params)}"


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    status: str = "",
    view: str = "cards",
    page_size: int = 10,
    page: int = 1,
) -> HTMLResponse:
    q = q.strip()
    selected_status = status if status in {value for value, _ in STATUS_OPTIONS} else ""
    view_mode = view if view in {"cards", "list"} else "cards"
    page_size = page_size if page_size in {10, 20, 50} else 10
    params: list[str] = []
    filters: list[str] = []
    if q.strip():
        filters.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if selected_status:
        filters.append("status = ?")
        params.append(selected_status)
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    with db_session() as connection:
        total_count = connection.execute(
            f"SELECT COUNT(*) FROM projects{where_clause}", params
        ).fetchone()[0]
        page_count = ceil(total_count / page_size) if total_count else 0
        page = min(max(page, 1), page_count) if page_count else 1
        projects = connection.execute(
            f"SELECT * FROM projects{where_clause} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()

    first_page = max(1, min(page - 2, page_count - 4)) if page_count else 0
    last_page = min(page_count, first_page + 4) if page_count else 0
    pagination_pages = [
        {
            "number": page_number,
            "url": project_list_url(q, selected_status, view_mode, page_size, page_number),
            "current": page_number == page,
        }
        for page_number in range(first_page, last_page + 1)
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        page_context(
            request,
            projects=projects,
            q=q,
            selected_status=selected_status,
            view_mode=view_mode,
            page_size=page_size,
            page_size_options=(10, 20, 50),
            page=page,
            page_count=page_count,
            total_count=total_count,
            first_result=(page - 1) * page_size + 1 if total_count else 0,
            last_result=min(page * page_size, total_count),
            pagination_pages=pagination_pages,
            previous_url=(
                project_list_url(q, selected_status, view_mode, page_size, page - 1)
                if page > 1 else ""
            ),
            next_url=(
                project_list_url(q, selected_status, view_mode, page_size, page + 1)
                if page < page_count else ""
            ),
            card_view_url=project_list_url(q, selected_status, "cards", page_size, page),
            list_view_url=project_list_url(q, selected_status, "list", page_size, page),
        ),
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
        vault_configured = connection.execute(
            "SELECT 1 FROM vault_config WHERE id = 1"
        ).fetchone() is not None
        settings = connection.execute(
            "SELECT allow_secret_export FROM app_settings WHERE id = 1"
        ).fetchone()
    values.update(
        vault_configured=vault_configured,
        vault_unlocked=current_vault_key(request) is not None,
        allow_secret_export=bool(settings["allow_secret_export"]) if settings else False,
    )
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


@app.post("/projects/{project_id}/accounts")
def add_access_account(
    request: Request,
    project_id: int,
    label: str = Form(...),
    category: str = Form("website"),
    environment: str = Form("test"),
    endpoint: str = Form(""),
    database_name: str = Form(""),
    username: str = Form(""),
    role_scope: str = Form(""),
    purpose: str = Form(""),
    owner: str = Form(""),
    secret_reference: str = Form(""),
    secret_value: str = Form(""),
) -> RedirectResponse:
    if not label.strip():
        raise HTTPException(status_code=400, detail="帳號或服務名稱不可為空白")
    if category not in {value for value, _ in ACCESS_ACCOUNT_CATEGORIES}:
        category = "other"
    if environment not in {value for value, _ in ACCESS_ENVIRONMENTS}:
        environment = "other"
    if len(secret_value) > 4096:
        raise HTTPException(status_code=400, detail="密碼欄位不可超過 4096 個字元")
    key = current_vault_key(request) if secret_value else None
    if secret_value and key is None:
        raise HTTPException(status_code=423, detail="請先解鎖保管庫再保存實際密碼")

    with db_session() as connection:
        get_project(connection, project_id)
        cursor = connection.execute(
            """
            INSERT INTO access_accounts
                (project_id, label, category, environment, endpoint, database_name,
                 username, role_scope, purpose, owner, secret_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, label.strip(), category, environment, endpoint.strip(),
             database_name.strip(), username.strip(), role_scope.strip(), purpose.strip(),
             owner.strip(), secret_reference.strip()),
        )
        account_id = int(cursor.lastrowid)
        if secret_value and key is not None:
            ciphertext, nonce = encrypt_secret(key, project_id, account_id, secret_value)
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = ?, secret_nonce = ? WHERE id = ?",
                (ciphertext, nonce, account_id),
            )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/accounts/{account_id}/edit")
def update_access_account(
    request: Request,
    account_id: int,
    label: str = Form(...),
    category: str = Form("website"),
    environment: str = Form("test"),
    endpoint: str = Form(""),
    database_name: str = Form(""),
    username: str = Form(""),
    role_scope: str = Form(""),
    purpose: str = Form(""),
    owner: str = Form(""),
    secret_reference: str = Form(""),
    secret_value: str = Form(""),
    delete_secret: bool = Form(False),
) -> RedirectResponse:
    if not label.strip():
        raise HTTPException(status_code=400, detail="帳號或服務名稱不可為空白")
    if category not in {value for value, _ in ACCESS_ACCOUNT_CATEGORIES}:
        category = "other"
    if environment not in {value for value, _ in ACCESS_ENVIRONMENTS}:
        environment = "other"
    if len(secret_value) > 4096:
        raise HTTPException(status_code=400, detail="密碼欄位不可超過 4096 個字元")
    if delete_secret and secret_value:
        raise HTTPException(status_code=400, detail="不能同時刪除並更新密碼")
    key = current_vault_key(request) if secret_value else None
    if secret_value and key is None:
        raise HTTPException(status_code=423, detail="請先解鎖保管庫再更新實際密碼")

    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM access_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此帳號資料")
        project_id = int(item["project_id"])
        connection.execute(
            """
            UPDATE access_accounts
            SET label = ?, category = ?, environment = ?, endpoint = ?, database_name = ?,
                username = ?, role_scope = ?, purpose = ?, owner = ?, secret_reference = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (label.strip(), category, environment, endpoint.strip(), database_name.strip(),
             username.strip(), role_scope.strip(), purpose.strip(), owner.strip(),
             secret_reference.strip(), account_id),
        )
        if delete_secret:
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = NULL, secret_nonce = NULL WHERE id = ?",
                (account_id,),
            )
        elif secret_value and key is not None:
            ciphertext, nonce = encrypt_secret(key, project_id, account_id, secret_value)
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = ?, secret_nonce = ? WHERE id = ?",
                (ciphertext, nonce, account_id),
            )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/accounts/{account_id}/delete")
def delete_access_account(account_id: int) -> RedirectResponse:
    with db_session() as connection:
        item = connection.execute(
            "SELECT project_id FROM access_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="找不到此帳號資料")
        project_id = int(item["project_id"])
        connection.execute("DELETE FROM access_accounts WHERE id = ?", (account_id,))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
    return redirect_to_project(project_id)


@app.post("/accounts/{account_id}/reveal")
def reveal_access_account_secret(request: Request, account_id: int) -> JSONResponse:
    key = require_vault_key(request)
    with db_session() as connection:
        item = connection.execute(
            """
            SELECT project_id, secret_ciphertext, secret_nonce
            FROM access_accounts WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="找不到此帳號資料")
    if item["secret_ciphertext"] is None or item["secret_nonce"] is None:
        raise HTTPException(status_code=404, detail="此帳號沒有保存密碼")
    try:
        secret_value = decrypt_secret(
            key,
            int(item["project_id"]),
            account_id,
            bytes(item["secret_ciphertext"]),
            bytes(item["secret_nonce"]),
        )
    except VaultError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    response = JSONResponse({"secret": secret_value})
    response.headers.update(
        {
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
    )
    return response


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


def access_environment_label(environment: str) -> str:
    return dict(ACCESS_ENVIRONMENTS).get(environment, environment)


def access_account_category_label(category: str) -> str:
    return dict(ACCESS_ACCOUNT_CATEGORIES).get(category, category)


templates.env.globals.update(
    access_environment_label=access_environment_label,
    access_account_category_label=access_account_category_label,
)


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


@app.get("/projects/{project_id}/export.pdf")
def export_pdf(project_id: int) -> Response:
    with db_session() as connection:
        values = project_detail(connection, project_id)
    project = values["project"]
    try:
        content = generate_project_pdf(
            project,
            values["urls"],
            values["notes"],
            values["checklist"],
            values["environment_variables"],
            values["access_accounts"],
        )
    except PDFExportError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    filename = f"{project['name']}.pdf".replace("/", "-").replace("\\", "-")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="projmemo-{project_id}.pdf"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


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
        values["access_accounts"],
    )
    filename = f"{project['name']}.md".replace("/", "-").replace("\\", "-")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="projmemo-{project_id}.md"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
        },
    )


def _sensitive_export_accounts(
    connection: sqlite3.Connection,
    project_id: int,
    key: bytes,
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT id, project_id, label, category, environment, endpoint, database_name,
               username, role_scope, purpose, owner, secret_reference,
               secret_ciphertext, secret_nonce
        FROM access_accounts WHERE project_id = ?
        ORDER BY label COLLATE NOCASE
        """,
        (project_id,),
    ).fetchall()
    accounts: list[dict[str, object]] = []
    for row in rows:
        account = {
            name: row[name]
            for name in (
                "label", "category", "environment", "endpoint", "database_name",
                "username", "role_scope", "purpose", "owner", "secret_reference",
            )
        }
        ciphertext = row["secret_ciphertext"]
        nonce = row["secret_nonce"]
        account["has_secret"] = ciphertext is not None and nonce is not None
        account["secret_value"] = (
            decrypt_secret(key, int(row["project_id"]), int(row["id"]), bytes(ciphertext), bytes(nonce))
            if ciphertext is not None and nonce is not None else None
        )
        accounts.append(account)
    return accounts


@app.post("/projects/{project_id}/export-with-secrets")
def export_project_with_secrets(
    request: Request,
    project_id: int,
    export_format: str = Form(...),
    confirm_sensitive_export: bool = Form(False),
) -> Response:
    if export_format not in {"markdown", "pdf"}:
        raise HTTPException(status_code=400, detail="不支援的匯出格式")
    if not confirm_sensitive_export:
        raise HTTPException(status_code=400, detail="請先確認此檔案包含實際密碼")
    key = require_vault_key(request)
    with db_session() as connection:
        setting = connection.execute(
            "SELECT allow_secret_export FROM app_settings WHERE id = 1"
        ).fetchone()
        if setting is None or not setting["allow_secret_export"]:
            raise HTTPException(status_code=403, detail="尚未在保管庫設定中允許含密碼匯出")
        values = project_detail(connection, project_id)
        access_accounts = _sensitive_export_accounts(connection, project_id, key)
    project = values["project"]
    if export_format == "markdown":
        content = build_markdown(
            project,
            values["urls"],
            values["notes"],
            values["checklist"],
            values["environment_variables"],
            access_accounts,
            include_secrets=True,
        )
        filename = f"{project['name']}.md".replace("/", "-").replace("\\", "-")
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="projmemo-{project_id}-sensitive.md"; '
                    f"filename*=UTF-8''{quote(filename)}"
                ),
                "Cache-Control": "no-store, private",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
            },
        )

    try:
        content = generate_project_pdf(
            project,
            values["urls"],
            values["notes"],
            values["checklist"],
            values["environment_variables"],
            access_accounts,
            include_secrets=True,
        )
    except PDFExportError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    filename = f"{project['name']}.pdf".replace("/", "-").replace("\\", "-")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="projmemo-{project_id}-sensitive.pdf"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )
