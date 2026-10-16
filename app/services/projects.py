"""Project queries and transaction boundaries, independent of HTTP."""

import sqlite3
from math import ceil
from urllib.parse import urlencode

from ..db import db_session
from ..errors import ApplicationError
from ..validation import normalize_fields
from ..options import STATUS_OPTIONS
from ..project_data import ProjectData
from ..project_search import PROGRESS_COLUMNS, filter_options, handover_progress, has_token, normalized_filters, project_where
from .vault import read_vault_settings


def get_project(connection: sqlite3.Connection, project_id: int, *, include_deleted: bool = False) -> sqlite3.Row:
    project = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None or ("deleted_at" in project.keys() and project["deleted_at"] and not include_deleted):
        raise ApplicationError(status_code=404, detail="找不到此專案")
    return project


def project_related(connection: sqlite3.Connection, project_id: int) -> dict:
    project = get_project(connection, project_id)
    return dict(
        project=project,
        urls=connection.execute(
            "SELECT * FROM project_urls WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
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


def project_detail(connection: sqlite3.Connection, project_id: int) -> ProjectData:
    related = project_related(connection, project_id)
    notes = connection.execute("SELECT * FROM notes WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    return ProjectData(**related, notes=notes)


def touch_project(connection: sqlite3.Connection, project_id: int) -> None:
    """Called inside the content mutation's existing transaction, never commit."""
    get_project(connection, project_id)  # A trashed parent rolls back the whole child mutation.
    connection.execute(
        "UPDATE projects SET updated_at = CURRENT_TIMESTAMP, revision = revision + 1 WHERE id = ?",
        (project_id,),
    )


def project_list_url(
    q: str,
    status: str,
    view_mode: str,
    page_size: int,
    page: int,
    collection: str = 'active',
    *, owner: str = '', tag: str = '', search_scope: str = 'basic', handover: str = '',
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
    if collection in {"archived", "trash"}:
        params["collection"] = collection
    for name, value in (("owner", owner), ("tag", tag), ("handover", handover)):
        if value:
            params[name] = value
    if search_scope == "all":
        params["search_scope"] = search_scope
    return f"/?{urlencode(params)}"


def list_projects(
    *,
    q: str = '',
    status: str = '',
    view: str = 'cards',
    page_size: int = 10,
    page: int = 1,
    collection: str = 'active',
    owner: str = '',
    tag: str = '',
    search_scope: str = 'basic',
    handover: str = '',
) -> dict[str, object]:
    selected_status = status if status in {value for value, _ in STATUS_OPTIONS} else ""
    view_mode = view if view in {"cards", "list"} else "cards"
    page_size = page_size if page_size in {10, 20, 50} else 10
    collection = collection if collection in {"active", "archived", "trash"} else "active"
    selected = normalized_filters(q=q, owner=owner, tag=tag, search_scope=search_scope,
                                  handover=handover, collection=collection)
    q = selected.pop("q")
    extra = selected
    where_clause, params = project_where(collection=collection, status=selected_status, q=q, **extra)
    with db_session() as connection:
        connection.create_function("projmemo_has_token", 2, has_token, deterministic=True)
        owner_options, tag_options = filter_options(connection, collection)
        collection_counts = dict(zip(("active", "archived", "trash"), connection.execute(
            "SELECT COALESCE(SUM(deleted_at = '' AND archived_at = ''), 0), "
            "COALESCE(SUM(deleted_at = '' AND archived_at != ''), 0), "
            "COALESCE(SUM(deleted_at != ''), 0) FROM projects"
        ).fetchone()))
        total_count = connection.execute(
            f"SELECT COUNT(*) FROM projects{where_clause}", params
        ).fetchone()[0]
        page_count = ceil(total_count / page_size) if total_count else 0
        page = min(max(page, 1), page_count) if page_count else 1
        projects = connection.execute(
            f"SELECT projects.*, {PROGRESS_COLUMNS} FROM projects{where_clause} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()

    first_page = max(1, min(page - 2, page_count - 4)) if page_count else 0
    last_page = min(page_count, first_page + 4) if page_count else 0
    pagination_pages = [
        {
            "number": page_number,
            "url": project_list_url(q, selected_status, view_mode, page_size, page_number, collection, **extra),
            "current": page_number == page,
        }
        for page_number in range(first_page, last_page + 1)
    ]
    return dict(
        projects=projects,
        collection=collection,
        collection_counts=collection_counts,
        collection_urls={scope: project_list_url(q, selected_status, view_mode, page_size, 1, scope, **extra)
                         for scope in ("active", "archived", "trash")},
        reset_list_url=project_list_url('', '', 'cards', 10, 1, collection),
        selected_owner=extra["owner"], selected_tag=extra["tag"], search_scope=extra["search_scope"],
        selected_handover=extra["handover"], owner_options=owner_options, tag_options=tag_options,
        has_filters=bool(q or selected_status or extra["owner"] or extra["tag"] or extra["handover"]),
        handover_progress={row["id"]: handover_progress(row["checklist_total"], row["checklist_completed"])
                           for row in projects},
        list_preferences={"view": view_mode, "page_size": page_size, "q": q, "status": selected_status,
                          **{key: value for key, value in extra.items()
                             if value and (key != "search_scope" or value != "basic")}},
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
        previous_url=project_list_url(q, selected_status, view_mode, page_size, page - 1, collection, **extra) if page > 1 else '',
        next_url=project_list_url(q, selected_status, view_mode, page_size, page + 1, collection, **extra) if page < page_count else '',
        card_view_url=project_list_url(q, selected_status, 'cards', page_size, page, collection, **extra),
        list_view_url=project_list_url(q, selected_status, 'list', page_size, page, collection, **extra),
        clear_filter_url=project_list_url('', '', view_mode, page_size, 1, collection)
    )


def create_project(
    *,
    name: str,
    description: str = '',
    status: str = 'maintenance',
    owner: str = '',
    tags: str = '',
) -> int:
    name, description, status, owner, tags = normalize_fields("project", locals())
    with db_session(write=True) as connection:
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
    name, description, status, owner, tags = normalize_fields("project", locals())
    with db_session(write=True) as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, status = ?, owner = ?, tags = ?,
                updated_at = CURRENT_TIMESTAMP, revision = revision + 1
            WHERE id = ?
            """,
            (name.strip(), description.strip(), status, owner.strip(), tags.strip(), project_id),
        )
    return int(project_id)


def load_project(project_id: int) -> sqlite3.Row:
    with db_session() as connection:
        return get_project(connection, project_id)


def project_for_item(kind: str, item_id: int) -> int:
    table = {"urls": "project_urls", "notes": "notes", "checklist": "checklist_items",
             "environment-variables": "environment_variables", "accounts": "access_accounts"}[kind]
    with db_session() as connection:
        row = connection.execute(f"SELECT project_id FROM {table} WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ApplicationError(404, "找不到此專案")
        get_project(connection, int(row["project_id"]))
        return int(row["project_id"])


def load_project_data(project_id: int) -> ProjectData:
    with db_session() as connection:
        return project_detail(connection, project_id)


def load_project_page(project_id: int) -> dict[str, object]:
    with db_session() as connection:
        values = project_detail(connection, project_id).template_context()
        configured, allow_export = read_vault_settings(connection)
    return {**values, "vault_configured": configured, "allow_secret_export": allow_export}
