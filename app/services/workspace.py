"""UI-only paged workspace. Never used by Markdown, PDF, or database backups."""

from math import ceil
from urllib.parse import urlencode

from ..db import db_session
from ..project_search import handover_progress
from .projects import project_related
from .vault import read_vault_settings


def bounded_number(value, default, maximum):
    try:
        number = int(value) if len(str(value)) <= 9 else default
    except (ValueError, TypeError):
        return default
    return min(max(number, 1), maximum)


def load_workspace(project_id, *, page="1", size="20", edit_note_id=None, notes_only=False, checklist_filter=""):
    size = bounded_number(size, 20, 100000000)
    size = size if size in {10, 20, 50} else 20
    checklist_filter = "pending" if checklist_filter == "pending" else ""
    with db_session() as connection:
        if notes_only:
            from .projects import get_project
            values = {"project": get_project(connection, project_id)}
        else:
            values = project_related(connection, project_id)
            configured, allow_export = read_vault_settings(connection)
            values.update(vault_configured=configured, allow_secret_export=allow_export)
            items = values["checklist"]
            values.update(checklist_progress=handover_progress(len(items), sum(item["completed"] for item in items)),
                          visible_checklist=[item for item in items if not checklist_filter or not item["completed"]])
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
        params = {"notes_page": number, "notes_size": count}
        if checklist_filter:
            params["checklist"] = checklist_filter
        return f"/projects/{project_id}?" + urlencode(params) + "#project-notes"
    def checklist_url(pending):
        params = {"notes_page": page, "notes_size": size}
        if pending:
            params["checklist"] = "pending"
        return f"/projects/{project_id}?" + urlencode(params) + "#handover"
    values.update(checklist_filter=checklist_filter,
                  checklist_urls={"all": checklist_url(False), "pending": checklist_url(True)},
                  note_total=total, note_page={
        "number": page, "size": size, "pages": pages, "total": total,
        "first": (page - 1) * size + 1 if total else 0, "last": min(page * size, total),
        "previous": url(page - 1) if page > 1 else "", "next": url(page + 1) if page < pages else "",
        "start": url(1), "end": url(pages), "sizes": [(count, url(1, count)) for count in (10, 20, 50)],
    })
    return values
