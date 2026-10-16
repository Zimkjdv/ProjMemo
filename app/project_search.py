"""Read-only project filters. No ciphertext, decryption, FTS or schema writes."""

from .errors import ApplicationError
from .validation import normalize_tokens


CONTENT_FIELDS = {
    "project_urls": ("title", "url", "note"),
    "notes": ("title", "content_markdown"),
    "checklist_items": ("title", "description", "owner", "note"),
    "environment_variables": ("key", "description", "source_or_owner"),
    "access_accounts": ("label", "endpoint", "database_name", "username", "role_scope",
                        "purpose", "owner", "secret_reference"),
}
COLLECTION_FILTERS = {"active": "projects.deleted_at = '' AND projects.archived_at = ''",
                      "archived": "projects.deleted_at = '' AND projects.archived_at != ''",
                      "trash": "projects.deleted_at != ''"}
PROGRESS_COLUMNS = (
    "(SELECT COUNT(*) FROM checklist_items WHERE project_id = projects.id) AS checklist_total, "
    "(SELECT COUNT(*) FROM checklist_items WHERE project_id = projects.id AND completed = 1) AS checklist_completed"
)


def has_token(value, token):
    """Exact, Unicode-casefolded member; legacy separators are read, not rewritten."""
    return int(isinstance(value, str) and token.casefold() in
               {part.casefold() for part in normalize_tokens(value).split(", ") if part})


def normalized_filters(*, q="", owner="", tag="", search_scope="basic", handover="", collection="active"):
    values = {"q": q.strip(), "owner": owner.strip(), "tag": tag.strip()}
    if any("\x00" in value or len(value) > (256 if name == "q" else 1000)
           for name, value in values.items()):
        raise ApplicationError(400, "搜尋字詞最多 256 字元，負責人與標籤最多 1000 字元，且不可包含空字元。")
    values.update(search_scope="all" if search_scope == "all" and collection != "trash" else "basic",
                  handover=handover if handover in {"pending", "complete", "none"} else "")
    return values


def search_conditions(pattern, include_content):
    clauses = ["(" + " OR ".join(f"projects.{name} LIKE ? ESCAPE '\\'"
               for name in ("name", "description", "tags", "owner")) + ")"]
    params = [pattern] * 4
    if include_content:
        for table, fields in CONTENT_FIELDS.items():
            body = " OR ".join(f"{table}.{name} LIKE ? ESCAPE '\\'" for name in fields)
            clauses.append(f"EXISTS (SELECT 1 FROM {table} WHERE {table}.project_id = projects.id AND ({body}))")
            params.extend([pattern] * len(fields))
    return "(" + " OR ".join(clauses) + ")", params


def project_where(*, collection, status, q, owner, tag, search_scope, handover):
    filters, params = [COLLECTION_FILTERS[collection]], []
    if q:
        # Treat %, _ and backslash as literal user text, not hidden wildcards.
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        expression, values = search_conditions(pattern, search_scope == "all")
        filters.append(expression)
        params.extend(values)
    if status:
        filters.append("projects.status = ?")
        params.append(status)
    for field, value in (("owner", owner), ("tags", tag)):
        if value:
            filters.append(f"projmemo_has_token(projects.{field}, ?) = 1")
            params.append(value)
    if handover == "pending":
        filters.append("EXISTS (SELECT 1 FROM checklist_items WHERE project_id = projects.id AND completed = 0)")
    elif handover == "complete":
        filters.extend(("EXISTS (SELECT 1 FROM checklist_items WHERE project_id = projects.id)",
                        "NOT EXISTS (SELECT 1 FROM checklist_items WHERE project_id = projects.id AND completed = 0)"))
    elif handover == "none":
        filters.append("NOT EXISTS (SELECT 1 FROM checklist_items WHERE project_id = projects.id)")
    return " WHERE " + " AND ".join(filters), params


def filter_options(connection, collection):
    # Only two short metadata columns from this collection; never load child bodies.
    rows = connection.execute("SELECT owner, tags FROM projects WHERE " + COLLECTION_FILTERS[collection] + " ORDER BY id")
    options = ({}, {})
    for row in rows:
        for index, value in enumerate(row):
            for token in normalize_tokens(value).split(", "):
                if token and len(options[index]) < 200:
                    options[index].setdefault(token.casefold(), token)
    return tuple(sorted(group.values(), key=str.casefold) for group in options)


def handover_progress(total, completed):
    return {"total": total, "completed": completed, "pending": total - completed,
            "percent": completed * 100 // total if total else None}
