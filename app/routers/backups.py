"""Backup uploads, downloads and HTML feedback; services own restoration."""

from datetime import datetime
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from ..backup import BackupRestoreError, BackupValidationError
from ..presentation import page_context, templates
from ..runtime import get_runtime
from ..services import backups
from ..web_security import NO_STORE_HEADERS


router = APIRouter()


def _backup_page(request: Request, *, restored: bool = False, error: str = "",
                 recovery_filename: str = "", status_code: int = 200) -> HTMLResponse:
    values = backups.backup_page_data(recovery_filename)
    return templates.TemplateResponse(request, "backup.html", page_context(
        request, restored=restored, error=error, **values,
    ), status_code=status_code)


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
def restore_database_backup(request: Request, backup_file: UploadFile = File(...)) -> Response:
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
