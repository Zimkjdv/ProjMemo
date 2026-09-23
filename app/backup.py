"""Safe SQLite backup and restore helpers for ProjMemo."""

from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import BinaryIO


MAX_BACKUP_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_COLUMNS = {
    "projects": {
        "id", "name", "description", "status", "owner", "tags", "created_at", "updated_at",
    },
    "project_urls": {"id", "project_id", "type", "title", "url", "note", "created_at"},
    "notes": {
        "id", "project_id", "category", "title", "content_markdown", "priority",
        "created_at", "updated_at",
    },
    "checklist_items": {
        "id", "project_id", "category", "title", "description", "owner", "completed",
        "note", "created_at", "updated_at",
    },
    "environment_variables": {
        "id", "project_id", "key", "environment", "description", "source_or_owner",
        "is_secret", "created_at", "updated_at",
    },
}
RECOVERY_FILENAME = re.compile(r"^projmemo-pre-restore-\d{8}-\d{6}-\d{6}\.sqlite3$")


class BackupValidationError(ValueError):
    """Raised when an uploaded file is not a valid ProjMemo database backup."""


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
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def validate_backup(path: Path) -> None:
    """Check SQLite integrity, ProjMemo's required schema, and safe schema objects."""
    try:
        with path.open("rb") as backup_file:
            if backup_file.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise BackupValidationError("檔案不是有效的 SQLite 資料庫備份。")

        connection = _read_only_connection(path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise BackupValidationError("備份檔的 SQLite 完整性檢查未通過。")

            objects = connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND type IN ('table', 'view', 'trigger')"
            ).fetchall()
            object_types = {name: kind for kind, name, _ in objects}
            missing_tables = set(REQUIRED_COLUMNS) - {
                name for name, kind in object_types.items() if kind == "table"
            }
            if missing_tables:
                raise BackupValidationError("備份檔缺少 ProjMemo 必要資料表，無法還原。")
            if any(
                kind in {"view", "trigger"}
                or (sql and sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE"))
                for kind, _, sql in objects
            ):
                raise BackupValidationError("備份檔包含不支援的資料庫物件，為安全起見無法還原。")

            for table, required_columns in REQUIRED_COLUMNS.items():
                columns = {
                    row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                if not required_columns <= columns:
                    raise BackupValidationError(
                        f"備份檔的「{table}」資料表欄位不完整，無法還原。"
                    )

            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupValidationError("備份檔含有不一致的關聯資料，無法還原。")
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


def _copy_database(source_path: Path, destination_path: Path) -> None:
    source = _read_only_connection(source_path)
    try:
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def create_database_backup(source_path: Path, destination_path: Path) -> None:
    """Create a transactionally consistent SQLite snapshot using SQLite's backup API."""
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("來源與備份目的地不可相同。")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
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


def restore_database(uploaded_path: Path, database_file: Path) -> Path:
    """Restore a validated backup, retaining a rollback snapshot before replacement."""
    validate_backup(uploaded_path)
    backups = recovery_directory(database_file)
    backups.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recovery_path = backups / f"projmemo-pre-restore-{timestamp}.sqlite3"
    create_database_backup(database_file, recovery_path)

    try:
        _copy_database(uploaded_path, database_file)
        validate_backup(database_file)
    except Exception as error:
        try:
            _copy_database(recovery_path, database_file)
            validate_backup(database_file)
        except Exception as recovery_error:
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
