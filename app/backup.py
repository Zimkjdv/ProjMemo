"""Safe SQLite backup and restore helpers for ProjMemo."""

from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import BinaryIO, Callable

from .db import init_db
from .database_access import access_for
from .schema_validation import (
    SchemaValidationError as BackupValidationError,
    validate_schema,
)
from .sqlite_policy import SQLITE_LOCK_WAIT_SECONDS, copy_database as _copy_database


MAX_BACKUP_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
SQLITE_HEADER = b"SQLite format 3\x00"
RECOVERY_FILENAME = re.compile(r"^projmemo-pre-(?:restore|delete)-\d{8}-\d{6}-\d{6}\.sqlite3$")


class BackupRestoreError(RuntimeError):
    """Raised when restore fails, with information about the recovery snapshot."""

    def __init__(self, message: str, recovery_filename: str, recovered: bool) -> None:
        super().__init__(message)
        self.recovery_filename = recovery_filename
        self.recovered = recovered


def recovery_directory(database_file: Path) -> Path:
    return database_file.parent / "backups"


def is_recovery_backup_filename(filename: str) -> bool:
    return RECOVERY_FILENAME.fullmatch(filename) is not None


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=SQLITE_LOCK_WAIT_SECONDS)
    connection.execute("PRAGMA query_only = ON")
    return connection


def validate_backup(path: Path) -> None:
    """Check a supported version before replacement; never migrate an upload."""
    try:
        with path.open("rb") as backup_file:
            if backup_file.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise BackupValidationError("檔案不是有效的 SQLite 資料庫備份。")

        connection = _read_only_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            validate_schema(connection)
        finally:
            connection.close()
    except BackupValidationError:
        raise
    except (OSError, sqlite3.DatabaseError) as error:
        raise BackupValidationError("無法讀取備份檔，請確認檔案完整且為 ProjMemo SQLite 備份。") from error


def save_uploaded_backup(upload: BinaryIO, destination_directory: Path) -> Path:
    """Stream an uploaded file to a private temporary path with a size limit."""
    destination_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".projmemo-upload-", suffix=".sqlite3", dir=destination_directory
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    total_bytes = 0

    try:
        with temporary_path.open("wb") as destination:
            while chunk := upload.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > MAX_BACKUP_BYTES:
                    raise BackupValidationError("備份檔不可超過 100 MB。")
                destination.write(chunk)

        if total_bytes == 0:
            raise BackupValidationError("請先選擇要還原的 SQLite 備份檔。")
        with temporary_path.open("rb") as uploaded:
            if uploaded.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise BackupValidationError("檔案不是有效的 SQLite 資料庫備份。")
        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def create_database_backup(source_path: Path, destination_path: Path) -> None:
    """Create a transactionally consistent SQLite snapshot using SQLite's backup API."""
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("來源與備份目的地不可相同。")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with access_for(source_path).operation():
        _copy_database(source_path, destination_path)


def create_temporary_backup(database_file: Path) -> Path:
    """Create a short-lived SQLite snapshot suitable for streaming to a browser."""
    descriptor, temporary_name = tempfile.mkstemp(prefix="projmemo-", suffix=".sqlite3")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        create_database_backup(database_file, temporary_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def create_deletion_snapshot(database_file: Path) -> Path:
    """Caller holds BEGIN IMMEDIATE; a separate reader copies the committed DB.

    Do not back up the caller's open write transaction: SQLite would wait on
    itself. An exclusive filename reservation also prevents snapshot overwrite.
    """
    directory = recovery_directory(database_file)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = directory / f"projmemo-pre-delete-{timestamp}.sqlite3"
    with destination.open("xb"):
        pass
    try:
        create_database_backup(database_file, destination)
        validate_backup(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def restore_database(
    uploaded_path: Path, database_file: Path, *,
    initialize: Callable[[Path], None] = init_db,
    on_replace: Callable[[], None] = lambda: None,
    expected_current: str | None = None,
) -> Path:
    """Restore a validated backup, retaining a rollback snapshot before replacement."""
    validate_backup(uploaded_path)
    access = access_for(database_file)
    with access.maintenance():
        backups = recovery_directory(database_file)
        backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        recovery_path = backups / f"projmemo-pre-restore-{timestamp}.sqlite3"
        create_database_backup(database_file, recovery_path)

        if expected_current is not None:
            from .backup_inspection import database_fingerprint
            from .errors import ApplicationError
            if database_fingerprint(recovery_path) != expected_current:
                raise ApplicationError(409, "目前資料已在預覽後變更，尚未替換；請重新預覽並確認。")

        try:
            on_replace()
            _copy_database(uploaded_path, database_file)
            initialize(database_file)
            validate_backup(database_file)
        except Exception as error:
            try:
                _copy_database(recovery_path, database_file)
                validate_backup(database_file)
            except Exception as recovery_error:
                access.require_recovery()
                raise BackupRestoreError(
                    "還原失敗，且自動回復未能完成。請保留並下載還原前備份。",
                    recovery_path.name,
                    recovered=False,
                ) from recovery_error
            raise BackupRestoreError(
                "還原失敗，已使用還原前備份回復原有資料。",
                recovery_path.name,
                recovered=True,
            ) from error

    return recovery_path
