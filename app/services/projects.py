"""Project queries and transaction boundaries, independent of HTTP."""

import sqlite3
from math import ceil
from urllib.parse import urlencode

from ..db import db_session
from ..errors import ApplicationError
from ..options import STATUS_OPTIONS
from ..project_data import ProjectData
from .vault import read_vault_settings


def get_project(connection: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    project = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise ApplicationError(status_code=404, detail="找不到此專案")
    return project


def project_detail(connection: sqlite3.Connection, project_id: int) -> ProjectData:
    project = get_project(connection, project_id)
    return ProjectData(
        project=project,
        urls=connection.execute(
            "SELECT * FROM project_urls WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall(),
        notes=connection.execute(
            "SELECT * FROM notes WHERE project_id = ? ORDER BY id DESC", (project_id,)
        ).fetchall(),
        checklist=connection.execute(
            "SELECT * FROM checklist_items WHERE project_id = ? ORDER BY completed, id DESC",
            (project_id,),
        ).fetchall(),
        environment_variables=connection.execute(
            """
            SELECT * FROM environment_variables
            WHERE project_id = ?
            ORDER BY CASE environment
                WHEN 'local' THEN 1 WHEN 'staging' THEN 2 WHEN 'production' THEN 3 ELSE 4
            END, key COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall(),
        access_accounts=[dict(row) for row in connection.execute(
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
    )


def touch_project(connection: sqlite3.Connection, project_id: int) -> None:
    """Called inside the content mutation's existing transaction, never commit."""
    connection.execute(
        "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (project_id,),
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


def list_projects(
    *,
    q: str = '',
    status: str = '',
    view: str = 'cards',
    page_size: int = 10,
    page: int = 1,
) -> dict[str, object]:
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
    return dict(
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
        previous_url=project_list_url(q, selected_status, view_mode, page_size, page - 1) if page > 1 else '',
        next_url=project_list_url(q, selected_status, view_mode, page_size, page + 1) if page < page_count else '',
        card_view_url=project_list_url(q, selected_status, 'cards', page_size, page),
        list_view_url=project_list_url(q, selected_status, 'list', page_size, page),
        clear_filter_url=project_list_url('', '', view_mode, page_size, 1)
    )


def create_project(
    *,
    name: str,
    description: str = '',
    status: str = 'maintenance',
    owner: str = '',
    tags: str = '',
) -> int:
    if not name.strip():
        raise ApplicationError(status_code=400, detail="專案名稱不可為空白")
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
    return int(project_id)


def update_project(
    *,
    project_id: int,
    name: str,
    description: str = '',
    status: str = 'maintenance',
    owner: str = '',
    tags: str = '',
) -> int:
    if not name.strip():
        raise ApplicationError(status_code=400, detail="專案名稱不可為空白")
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
    return int(project_id)


def load_project(project_id: int) -> sqlite3.Row:
    with db_session() as connection:
        return get_project(connection, project_id)


def load_project_data(project_id: int) -> ProjectData:
    with db_session() as connection:
        return project_detail(connection, project_id)


def load_project_page(project_id: int) -> dict[str, object]:
    with db_session() as connection:
        values = project_detail(connection, project_id).template_context()
        configured, allow_export = read_vault_settings(connection)
    return {**values, "vault_configured": configured, "allow_secret_export": allow_export}
