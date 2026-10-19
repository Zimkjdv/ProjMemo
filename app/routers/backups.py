"""Backup uploads, downloads and HTML feedback; services own restoration."""

from datetime import datetime
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from ..backup import BackupRestoreError, BackupValidationError
from ..errors import ApplicationError
from ..presentation import page_context, templates
from ..runtime import get_runtime
from ..services import backups
from ..web_security import NO_STORE_HEADERS


router = APIRouter()


def _binary_upload_schema(schema):
    # Preserve the existing multipart OpenAPI contract across Pydantic updates.
    schema.pop("contentMediaType", None)
    schema["format"] = "binary"


def _backup_page(request: Request, *, restored: bool = False, error: str = "",
                 recovery_filename: str = "", status_code: int = 200,
                 restore_preview=None, cleanup_preview=None, cleanup_result=None) -> HTMLResponse:
    values = backups.backup_page_data(recovery_filename)
    if request.method == "POST":
        # A language switch must return to a safe GET, not a POST-only preview URL.
        values["return_to"] = "/settings/backup"
        values["safe_return_to"] = "/settings/backup"
    return templates.TemplateResponse(request, "backup.html", page_context(
        request, restored=restored, error=error, restore_preview=restore_preview,
        cleanup_preview=cleanup_preview, cleanup_result=cleanup_result, **values,
    ), status_code=status_code, headers=NO_STORE_HEADERS)


@router.get("/settings/backup", response_class=HTMLResponse)
def backup_settings(request: Request, restored: bool = False, recovery: str = "") -> HTMLResponse:
    return _backup_page(request, restored=restored, recovery_filename=recovery)


@router.get("/settings/backup/download")
def download_database_backup() -> FileResponse:
    path = backups.database_snapshot()
    filename = f"projmemo-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=filename,
                        background=BackgroundTask(backups.remove_temporary_backup, path), headers=NO_STORE_HEADERS)


@router.post("/settings/backup/restore")
def restore_database_backup(request: Request, backup_file: UploadFile = File(..., json_schema_extra=_binary_upload_schema)) -> Response:
    try:
        recovery_path = backups.restore_upload(backup_file.file, get_runtime(request))
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
        return _backup_page(request, error="還原作業失敗，資料未完成替換。請確認磁碟空間與檔案權限。", status_code=500)
    finally:
        backup_file.file.close()
    return RedirectResponse(
        url=f"/settings/backup?restored=1&recovery={quote(recovery_path.name)}",
        status_code=303,
    )


@router.get("/settings/backup/files/{filename}")
def download_recovery_backup(filename: str) -> FileResponse:
    return FileResponse(backups.recovery_backup_path(filename), media_type="application/vnd.sqlite3",
                        filename=filename, headers=NO_STORE_HEADERS)


@router.post("/settings/backup/preview", response_class=HTMLResponse)
def preview_database_backup(request: Request, backup_file: UploadFile = File(..., json_schema_extra=_binary_upload_schema)):
    try:
        preview = backups.preview_upload(backup_file.file, get_runtime(request), request.state.csrf_token)
        return _backup_page(request, restore_preview=preview)
    except (BackupValidationError, ApplicationError) as error:
        return _backup_page(request, error=str(error) if isinstance(error, BackupValidationError) else error.detail,
                            status_code=getattr(error, "status_code", 400))
    except (OSError, sqlite3.Error):
        return _backup_page(request, error="預覽作業失敗，資料尚未變更。請確認磁碟空間與檔案權限。", status_code=500)
    finally:
        backup_file.file.close()


@router.post("/settings/backup/restore/confirm")
def confirm_database_restore(request: Request, preview_token: str = Form(...), confirmation: str = Form(""), acknowledged: str = Form("")):
    try:
        recovery_path = backups.confirm_restore(get_runtime(request), request.state.csrf_token,
                                                preview_token, confirmation, acknowledged)
    except ApplicationError as error:
        preview = (backups.existing_preview(get_runtime(request), request.state.csrf_token, preview_token, "restore")
                   if error.status_code == 400 else None)
        return _backup_page(request, error=error.detail, status_code=error.status_code, restore_preview=preview)
    except BackupValidationError as error:
        return _backup_page(request, error=str(error), status_code=400)
    except BackupRestoreError as error:
        return _backup_page(request, error=str(error), recovery_filename=error.recovery_filename, status_code=500)
    except (OSError, sqlite3.Error):
        return _backup_page(request, error="還原作業失敗，資料未完成替換。請確認磁碟空間與檔案權限。", status_code=500)
    return RedirectResponse(f"/settings/backup?restored=1&recovery={quote(recovery_path.name)}", 303, headers=NO_STORE_HEADERS)


@router.post("/settings/backup/preview/cancel")
def cancel_backup_preview(request: Request, preview_token: str = Form(...), kind: str = Form(...)):
    backups.cancel_preview(get_runtime(request), request.state.csrf_token, preview_token, kind)
    return RedirectResponse("/settings/backup", 303, headers=NO_STORE_HEADERS)


@router.post("/settings/backup/retention")
def save_backup_retention(request: Request, mode: str = Form(...), keep_count: str = Form("10"), min_age_days: str = Form("30")):
    try:
        backups.update_retention(mode, keep_count, min_age_days)
    except ApplicationError as error:
        return _backup_page(request, error=error.detail, status_code=error.status_code)
    except OSError:
        return _backup_page(request, error="保留策略未儲存，請確認磁碟空間與檔案權限。", status_code=500)
    return RedirectResponse("/settings/backup?notice=saved", 303, headers=NO_STORE_HEADERS)


@router.post("/settings/backup/cleanup/preview", response_class=HTMLResponse)
def preview_backup_cleanup(request: Request):
    try:
        return _backup_page(request, cleanup_preview=backups.preview_cleanup(get_runtime(request), request.state.csrf_token))
    except ApplicationError as error:
        return _backup_page(request, error=error.detail, status_code=error.status_code)
    except OSError:
        return _backup_page(request, error="預覽作業失敗，資料尚未變更。請確認磁碟空間與檔案權限。", status_code=500)


@router.post("/settings/backup/cleanup/confirm", response_class=HTMLResponse)
def confirm_backup_cleanup(request: Request, preview_token: str = Form(...), confirmation: str = Form(""), acknowledged: str = Form("")):
    try:
        result = backups.confirm_cleanup(get_runtime(request), request.state.csrf_token,
                                          preview_token, confirmation, acknowledged)
        return _backup_page(request, cleanup_result=result)
    except ApplicationError as error:
        preview = (backups.existing_preview(get_runtime(request), request.state.csrf_token, preview_token, "cleanup")
                   if error.status_code == 400 else None)
        return _backup_page(request, error=error.detail, status_code=error.status_code, cleanup_preview=preview)
    except OSError:
        return _backup_page(request, error="清理未完成，請保留其餘復原點並檢查檔案權限。", status_code=500)
