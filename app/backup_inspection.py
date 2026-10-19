"""Read-only backup summaries and logical state markers; never decrypt secrets."""

import hashlib

from .backup import _read_only_connection, validate_backup


def database_fingerprint(path):
    connection = _read_only_connection(path)
    try:
        connection.execute("BEGIN")
        digest = hashlib.sha256()
        def add(value):
            # Length and type framing preserves embedded NULs and field boundaries.
            # SQLite quote()/iterdump() truncates TEXT at NUL and is not a safe marker.
            if value is None:
                payload = b"N"
            elif isinstance(value, bytes):
                payload = b"B" + value
            elif isinstance(value, str):
                payload = b"T" + value.encode("utf-8")
            elif isinstance(value, int):
                payload = b"I" + str(value).encode("ascii")
            else:
                payload = b"F" + value.hex().encode("ascii")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
        add(connection.execute("PRAGMA user_version").fetchone()[0])
        objects = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        for row in objects:
            for value in row:
                add(value)
        for kind, name, _, _ in objects:
            if kind != "table":
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            keys = [row[1] for row in sorted(columns, key=lambda column: column[5]) if row[5]]
            keys = keys or [row[1] for row in columns]
            order = ",".join('"' + key.replace('"', '""') + '"' for key in keys)
            add(name)
            for row in connection.execute(f"SELECT * FROM {quoted} ORDER BY {order}"):
                add(len(row))
                for value in row:
                    add(value)
        return digest.hexdigest()
    finally:
        connection.close()


def inspect_backup(path):
    validate_backup(path)
    connection = _read_only_connection(path)
    try:
        connection.execute("BEGIN")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                  if table in tables else 0 for table in (
                      "projects", "project_urls", "notes", "checklist_items", "environment_variables", "access_accounts")}
        if version >= 4:
            active, archived, trash = connection.execute(
                "SELECT COALESCE(SUM(deleted_at='' AND archived_at=''),0), "
                "COALESCE(SUM(deleted_at='' AND archived_at!=''),0), COALESCE(SUM(deleted_at!=''),0) FROM projects"
            ).fetchone()
        else:
            active, archived, trash = counts["projects"], 0, 0
        initialized = "vault_config" in tables and connection.execute("SELECT COUNT(*) FROM vault_config").fetchone()[0] == 1
        secret_count = (connection.execute("SELECT COUNT(*) FROM access_accounts WHERE secret_ciphertext IS NOT NULL").fetchone()[0]
                        if "access_accounts" in tables else 0)
        allow_export = (bool(connection.execute("SELECT allow_secret_export FROM app_settings WHERE id=1").fetchone()[0])
                        if "app_settings" in tables else False)
        return {"version": version, "counts": counts, "active": active, "archived": archived, "trash": trash,
                "vault_initialized": initialized, "secret_count": secret_count, "allow_secret_export": allow_export}
    finally:
        connection.close()
