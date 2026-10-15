"""UI-only paged workspace. Never used by Markdown, PDF, or database backups."""

from math import ceil
from urllib.parse import urlencode

from ..db import db_session
from .projects import project_related
from .vault import read_vault_settings


def bounded_number(value, default, maximum):
    try:
        number = int(value) if len(str(value)) <= 9 else default
    except (ValueError, TypeError):
        return default
    return min(max(number, 1), maximum)


def load_workspace(project_id, *, page="1", size="20", edit_note_id=None, notes_only=False):
    size = bounded_number(size, 20, 100000000)
    size = size if size in {10, 20, 50} else 20
    with db_session() as connection:
        if notes_only:
            from .projects import get_project
            values = {"project": get_project(connection, project_id)}
        else:
            values = project_related(connection, project_id)
            configured, allow_export = read_vault_settings(connection)
            values.update(vault_configured=configured, allow_secret_export=allow_export)
        total = connection.execute("SELECT COUNT(*) FROM notes WHERE project_id = ?", (project_id,)).fetchone()[0]
        pages = max(1, ceil(total / size))
        page = bounded_number(page, 1, pages)
        if edit_note_id is not None:
            rank = connection.execute("SELECT COUNT(*) FROM notes WHERE project_id = ? AND id > ?", (project_id, edit_note_id)).fetchone()[0]
            page = min(rank // size + 1, pages)
        values["notes"] = connection.execute(
            "SELECT * FROM notes WHERE project_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (project_id, size, (page - 1) * size),
        ).fetchall()
    def url(number, count=size):
        return f"/projects/{project_id}?" + urlencode({"notes_page": number, "notes_size": count}) + "#project-notes"
    values.update(note_total=total, note_page={
        "number": page, "size": size, "pages": pages, "total": total,
        "first": (page - 1) * size + 1 if total else 0, "last": min(page * size, total),
        "previous": url(page - 1) if page > 1 else "", "next": url(page + 1) if page < pages else "",
        "start": url(1), "end": url(pages), "sizes": [(count, url(1, count)) for count in (10, 20, 50)],
    })
    return values
