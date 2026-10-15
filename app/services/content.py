"""URL, note, checklist and environment mutations with atomic project timestamps."""

from ..db import db_session
from ..errors import ApplicationError
from ..validation import normalize_fields
from .projects import get_project, touch_project


def add_url(*, project_id: int, type: str = 'other', title: str, url: str, note: str = '') -> int:
    type, title, url, note = normalize_fields("url", locals())
    with db_session(write=True) as connection:
        get_project(connection, project_id)
        connection.execute(
            "INSERT INTO project_urls (project_id, type, title, url, note) VALUES (?, ?, ?, ?, ?)",
            (project_id, type, title.strip(), url.strip(), note.strip()),
        )
        touch_project(connection, project_id)
    return int(project_id)


def update_url(*, url_id: int, type: str = 'other', title: str, url: str, note: str = '') -> int:
    type, title, url, note = normalize_fields("url", locals())
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM project_urls WHERE id = ?", (url_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此 URL")
        project_id = item["project_id"]
        connection.execute(
            """
            UPDATE project_urls SET type = ?, title = ?, url = ?, note = ?
            WHERE id = ?
            """,
            (type, title.strip(), url.strip(), note.strip(), url_id),
        )
        touch_project(connection, project_id)
    return int(project_id)


def delete_url(*, url_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM project_urls WHERE id = ?", (url_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此 URL")
        project_id = item["project_id"]
        connection.execute("DELETE FROM project_urls WHERE id = ?", (url_id,))
        touch_project(connection, project_id)
    return int(project_id)


def add_note(
    *,
    project_id: int,
    category: str = 'note',
    title: str,
    content_markdown: str,
    priority: str = 'normal',
) -> int:
    category, title, content_markdown, priority = normalize_fields("note", locals())
    with db_session(write=True) as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            INSERT INTO notes (project_id, category, title, content_markdown, priority)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, category, title.strip(), content_markdown.strip(), priority),
        )
        touch_project(connection, project_id)
    return int(project_id)


def update_note(
    *,
    note_id: int,
    category: str = 'note',
    title: str,
    content_markdown: str,
    priority: str = 'normal',
) -> int:
    category, title, content_markdown, priority = normalize_fields("note", locals())
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此備註")
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
        touch_project(connection, project_id)
    return int(project_id)


def delete_note(*, note_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此備註")
        project_id = item["project_id"]
        connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        touch_project(connection, project_id)
    return int(project_id)


def add_checklist_item(
    *,
    project_id: int,
    category: str = 'other',
    title: str,
    description: str = '',
    owner: str = '',
    note: str = '',
) -> int:
    category, title, description, owner, note = normalize_fields("checklist", locals())
    with db_session(write=True) as connection:
        get_project(connection, project_id)
        connection.execute(
            """
            INSERT INTO checklist_items
                (project_id, category, title, description, owner, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, category, title.strip(), description.strip(), owner.strip(), note.strip()),
        )
        touch_project(connection, project_id)
    return int(project_id)


def toggle_checklist(*, item_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id, completed FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此交接項目")
        connection.execute(
            """
            UPDATE checklist_items
            SET completed = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (0 if item["completed"] else 1, item_id),
        )
        touch_project(connection, item["project_id"])
        project_id = item["project_id"]
    return int(project_id)


def update_checklist_item(
    *,
    item_id: int,
    category: str = 'other',
    title: str,
    description: str = '',
    owner: str = '',
    note: str = '',
) -> int:
    category, title, description, owner, note = normalize_fields("checklist", locals())
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此交接項目")
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
        touch_project(connection, project_id)
    return int(project_id)


def delete_checklist_item(*, item_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM checklist_items WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此交接項目")
        project_id = item["project_id"]
        connection.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
        touch_project(connection, project_id)
    return int(project_id)


def add_environment_variable(
    *,
    project_id: int,
    key: str,
    environment: str = 'local',
    description: str = '',
    source_or_owner: str = '',
    is_secret: bool = False,
) -> int:
    key, environment, description, source_or_owner = normalize_fields("environment", locals())
    with db_session(write=True) as connection:
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
        touch_project(connection, project_id)
    return int(project_id)


def update_environment_variable(
    *,
    variable_id: int,
    key: str,
    environment: str = 'local',
    description: str = '',
    source_or_owner: str = '',
    is_secret: bool = False,
) -> int:
    key, environment, description, source_or_owner = normalize_fields("environment", locals())
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM environment_variables WHERE id = ?", (variable_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此環境變數")
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
        touch_project(connection, project_id)
    return int(project_id)


def delete_environment_variable(*, variable_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM environment_variables WHERE id = ?", (variable_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此環境變數")
        project_id = item["project_id"]
        connection.execute("DELETE FROM environment_variables WHERE id = ?", (variable_id,))
        touch_project(connection, project_id)
    return int(project_id)
