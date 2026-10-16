"""Recoverable project lifecycle, independent of business status and HTTP."""

import sqlite3

from ..backup import create_deletion_snapshot
from ..db import database_path, db_session
from ..errors import ApplicationError
from ..runtime import AppRuntime
from .projects import get_project


CHILD_TABLES = ("project_urls", "notes", "checklist_items", "environment_variables", "access_accounts")


def management_data(project_id: int) -> dict:
    with db_session() as connection:
        project = get_project(connection, project_id, include_deleted=True)
        counts = {table: connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
        ).fetchone()[0] for table in CHILD_TABLES}
    return {"project": project, "related_counts": counts,
            "lifecycle_state": "trash" if project["deleted_at"] else
                               "archived" if project["archived_at"] else "active"}


def transition(*, project_id: int, action: str, revision: int,
               confirmation_name: str, confirmed: bool, runtime: AppRuntime) -> str:
    """Check current state under the same writer lock as snapshot and mutation.

    Revision changes on every content/lifecycle write, not wall-clock seconds.
    Restoring leaves archived_at intact, so the original collection is retained.
    """
    if action not in {"archive", "unarchive", "trash", "restore", "purge"}:
        raise ApplicationError(404, "找不到此操作")
    with db_session(write=True) as connection:
        project = get_project(connection, project_id, include_deleted=True)
        if revision != project["revision"]:
            raise ApplicationError(409, "專案已變更，請重新檢查內容與數量後再確認。")
        if not confirmed or confirmation_name != project["name"]:
            raise ApplicationError(400, "請輸入完整專案名稱並勾選確認。")
        deleted, archived = bool(project["deleted_at"]), bool(project["archived_at"])
        allowed = {"archive": not deleted and not archived,
                   "unarchive": not deleted and archived,
                   "trash": not deleted, "restore": deleted, "purge": deleted}
        if not allowed[action]:
            raise ApplicationError(409, "專案狀態已變更，請重新整理後再操作。")
        if action == "purge":
            try:
                create_deletion_snapshot(database_path())
            except (OSError, sqlite3.Error, ValueError) as error:
                raise ApplicationError(503, "無法建立或驗證刪除前復原點，本次未刪除任何資料。") from error
            # Foreign keys are enabled by db_session. Never touch global vault settings.
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            destination = "/?collection=trash"
        else:
            assignment = {"archive": "archived_at = CURRENT_TIMESTAMP",
                          "unarchive": "archived_at = ''",
                          "trash": "deleted_at = CURRENT_TIMESTAMP",
                          "restore": "deleted_at = ''"}[action]
            connection.execute(
                f"UPDATE projects SET {assignment}, revision = revision + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
            )
            destination = f"/projects/{project_id}/manage"
    # Revoke open secret views only after a successful commit, never on validation failure.
    if action in {"trash", "purge"}:
        runtime.vault_sessions.clear()
    return destination
