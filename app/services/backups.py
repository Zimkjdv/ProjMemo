"""Backup orchestration and recovery-file selection, without HTTP resources."""

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import BinaryIO

from ..backup import (
    create_temporary_backup, is_recovery_backup_filename, recovery_directory,
    restore_database, save_uploaded_backup,
)
from ..database_access import DatabaseBusyError
from ..db import database_path, db_session, init_db
from ..errors import ApplicationError
from ..runtime import AppRuntime


def backup_page_data(recovery_filename: str = "") -> dict[str, object]:
    try:
        with db_session() as connection:
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    except (sqlite3.Error, DatabaseBusyError):
        project_count = None
    directory = recovery_directory(database_path())
    recovery_backups = []
    try:
        paths = sorted((path for path in directory.glob("projmemo-pre-*.sqlite3")
                        if is_recovery_backup_filename(path.name) and not path.is_symlink()),
                       key=lambda path: path.stat().st_mtime, reverse=True)[:10]
        for path in paths:
            stats = path.stat()
            recovery_backups.append({
                "filename": path.name,
                "before_delete": path.name.startswith("projmemo-pre-delete-"),
                "created_at": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_mb": max(stats.st_size / (1024 * 1024), 0.01),
            })
    except OSError:
        recovery_backups = []
    if (not is_recovery_backup_filename(recovery_filename)
            or not (directory / recovery_filename).is_file()):
        recovery_filename = ""
    return {"project_count": project_count, "recovery_backups": recovery_backups,
            "recovery_filename": recovery_filename}


def database_snapshot() -> Path:
    return create_temporary_backup(database_path())


def remove_temporary_backup(path: Path) -> None:
    path.unlink(missing_ok=True)


def restore_upload(upload: BinaryIO, runtime: AppRuntime) -> Path:
    uploaded_path = None
    try:
        uploaded_path = save_uploaded_backup(upload, database_path().parent)
        return restore_database(uploaded_path, database_path(), initialize=init_db,
                                on_replace=runtime.vault_sessions.clear)
    finally:
        if uploaded_path is not None:
            uploaded_path.unlink(missing_ok=True)


def recovery_backup_path(filename: str) -> Path:
    if not is_recovery_backup_filename(filename):
        raise ApplicationError(404, "找不到此備份檔")
    path = recovery_directory(database_path()) / filename
    directory = recovery_directory(database_path()).resolve()
    try:
        if path.is_symlink() or path.resolve().parent != directory:
            raise ApplicationError(404, "找不到此備份檔")
    except OSError as error:
        raise ApplicationError(404, "找不到此備份檔") from error
    if not path.is_file():
        raise ApplicationError(404, "找不到此備份檔")
    return path
