"""Backup orchestration and recovery-file selection, without HTTP resources."""

from pathlib import Path
import sqlite3
from typing import BinaryIO

from ..backup import (
    create_temporary_backup, is_recovery_backup_filename,
    restore_database, save_uploaded_backup,
)
from ..backup_inspection import database_fingerprint, inspect_backup
from ..backup_activity import read_download_activity, record_download_generation
from .. import backup_retention as retention
from ..database_access import DatabaseBusyError
from ..database_access import access_for
from ..db import database_path, db_session, init_db
from ..errors import ApplicationError
from ..migrations import SCHEMA_VERSION
from ..runtime import AppRuntime


def backup_page_data(recovery_filename: str = "") -> dict[str, object]:
    try:
        with db_session() as connection:
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    except (sqlite3.Error, DatabaseBusyError):
        project_count = None
    recovery_backups = []
    recovery_count = None
    try:
        records = retention.recovery_files(database_path())
        recovery_count = len(records)
        for record in records[:10]:
            recovery_backups.append({
                "filename": record["filename"],
                "before_delete": record["filename"].startswith("projmemo-pre-delete-"),
                "before_vault_change": record["filename"].startswith("projmemo-pre-vault-change-"),
                "created_at": record["created_at"],
                "size_mb": max(record["size"] / (1024 * 1024), 0.01),
            })
    except (OSError, ApplicationError):
        recovery_backups = []
    try:
        recovery_backup_path(recovery_filename)
    except ApplicationError:
        recovery_filename = ""
    policy_error = ""
    try:
        policy = retention.read_policy(database_path())
    except ApplicationError as error:
        policy, policy_error = dict(retention.DEFAULT_POLICY), error.detail
    return {"project_count": project_count, "recovery_backups": recovery_backups, "recovery_count": recovery_count,
            "download_activity": read_download_activity(database_path()),
            "recovery_filename": recovery_filename, "retention_policy": policy,
            "policy_error": policy_error, "target_schema_version": SCHEMA_VERSION}


def database_snapshot() -> Path:
    return create_temporary_backup(database_path())


def download_snapshot() -> Path:
    path = database_snapshot()
    record_download_generation(database_path())
    return path


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
    try:
        directory = retention.safe_directory(database_path()).resolve()
    except ApplicationError:
        raise ApplicationError(404, "找不到此備份檔") from None
    path = directory / filename
    try:
        if path.is_symlink() or path.is_junction() or path.resolve().parent != directory:
            raise ApplicationError(404, "找不到此備份檔")
        if path.is_file() and path.stat().st_nlink != 1:
            raise ApplicationError(404, "找不到此備份檔")
    except OSError as error:
        raise ApplicationError(404, "找不到此備份檔") from error
    if not path.is_file():
        raise ApplicationError(404, "找不到此備份檔")
    return path


def preview_recovery(filename: str, runtime: AppRuntime, browser: str) -> dict:
    # Copy to the same private, bounded upload used by regular previews. The
    # original recovery point is never consumed or directly restored by this UI.
    with recovery_backup_path(filename).open("rb") as stream:
        return preview_upload(stream, runtime, browser)


def preview_upload(upload: BinaryIO, runtime: AppRuntime, browser: str) -> dict:
    uploaded = save_uploaded_backup(upload, database_path().parent)
    snapshot = None
    try:
        incoming = inspect_backup(uploaded)
        snapshot = database_snapshot()
        current = inspect_backup(snapshot)
        values = {"incoming": incoming, "current": current, "size_mb": uploaded.stat().st_size / 1024**2,
                  "incoming_marker": database_fingerprint(uploaded), "current_marker": database_fingerprint(snapshot)}
        token = runtime.backup_plans.issue(browser, database_path(), "restore", values, upload=uploaded)
        return {**values, "token": token}
    except Exception:
        uploaded.unlink(missing_ok=True)
        raise
    finally:
        if snapshot is not None:
            remove_temporary_backup(snapshot)


def confirm_restore(runtime: AppRuntime, browser: str, token: str, confirmation: str, acknowledged: str) -> Path:
    if confirmation != "RESTORE" or acknowledged != "yes":
        raise ApplicationError(400, "請勾選替換確認，並輸入 RESTORE 後再還原。")
    with runtime.backup_plans.consume(token, browser, database_path(), "restore") as plan:
        if plan.upload is None or database_fingerprint(plan.upload) != plan.values["incoming_marker"]:
            raise ApplicationError(409, "預覽檔案已變更，尚未替換；請重新上傳。")
        return restore_database(plan.upload, database_path(), initialize=init_db,
                                on_replace=runtime.vault_sessions.clear,
                                expected_current=plan.values["current_marker"])


def existing_preview(runtime: AppRuntime, browser: str, token: str, kind: str):
    try:
        plan = runtime.backup_plans.get(token, browser, database_path(), kind)
        return {**plan.values, "token": token}
    except ApplicationError:
        return None


def cancel_preview(runtime: AppRuntime, browser: str, token: str, kind: str) -> None:
    if kind not in {"restore", "cleanup"}:
        raise ApplicationError(409, "預覽已失效或不屬於此瀏覽器，請重新預覽。")
    with runtime.backup_plans.consume(token, browser, database_path(), kind):
        pass


def update_retention(mode: str, keep_count: str, min_age_days: str) -> None:
    retention.save_policy(database_path(), retention.normalized_policy(mode, keep_count, min_age_days))


def preview_cleanup(runtime: AppRuntime, browser: str) -> dict:
    policy = retention.read_policy(database_path())
    candidates = retention.cleanup_candidates(database_path(), policy)
    retention.verify_retained_copy(database_path(), candidates)
    values = {"policy": policy, "candidates": candidates, "size_mb": sum(item["size"] for item in candidates) / 1024**2}
    if not candidates:
        return {**values, "token": ""}
    token = runtime.backup_plans.issue(browser, database_path(), "cleanup", values)
    return {**values, "token": token}


def confirm_cleanup(runtime: AppRuntime, browser: str, token: str, confirmation: str, acknowledged: str) -> dict:
    if confirmation != "DELETE" or acknowledged != "yes":
        raise ApplicationError(400, "請勾選清理確認，並輸入 DELETE 後再清理。")
    with runtime.backup_plans.consume(token, browser, database_path(), "cleanup") as plan:
        with access_for(database_path()).maintenance():
            policy = retention.read_policy(database_path())
            candidates = retention.cleanup_candidates(database_path(), policy)
            if policy != plan.values["policy"] or candidates != plan.values["candidates"]:
                raise ApplicationError(409, "復原點已變更，本次未清理，請重新預覽。")
            retention.verify_retained_copy(database_path(), candidates)
            return retention.delete_candidates(database_path(), candidates)
