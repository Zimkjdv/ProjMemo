"""Read-only schema/data checks shared by startup migrations and backup restore."""

import sqlite3
import re

from .migrations import LIFECYCLE_INDEXES, MIGRATIONS, QUERY_INDEXES, SCHEMA_VERSION
from .vault import VaultError, validate_vault_metadata


class SchemaValidationError(ValueError):
    """A database does not match a supported ProjMemo schema."""


REQUIRED_COLUMNS = {
    "projects": {
        "id", "name", "description", "status", "owner", "tags", "created_at", "updated_at",
    },
    "project_urls": {"id", "project_id", "type", "title", "url", "note", "created_at"},
    "notes": {
        "id", "project_id", "category", "title", "content_markdown", "priority", "created_at", "updated_at",
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
VAULT_COLUMNS = {
    "access_accounts": {
        "id", "project_id", "label", "category", "environment", "endpoint",
        "database_name", "username", "role_scope", "purpose", "owner", "secret_reference",
        "secret_ciphertext", "secret_nonce", "created_at", "updated_at",
    },
    "vault_config": {
        "id", "salt", "verifier_nonce", "verifier_ciphertext", "kdf_memory_cost",
        "kdf_iterations", "kdf_lanes", "created_at",
    },
    "app_settings": {"id", "allow_secret_export"},
}
INTEGER_COLUMNS = {"id", "project_id", "completed", "is_secret", "allow_secret_export",
                   "kdf_memory_cost", "kdf_iterations", "kdf_lanes", "version", "revision"}
BLOB_COLUMNS = {"secret_ciphertext", "secret_nonce", "salt", "verifier_nonce", "verifier_ciphertext"}


def validate_schema(connection: sqlite3.Connection) -> int:
    """Validate this connection's snapshot, including uncommitted migration DDL."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in range(SCHEMA_VERSION + 1):
        raise SchemaValidationError("備份檔的資料版本不受支援，請先升級 ProjMemo。")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise SchemaValidationError("備份檔的 SQLite 完整性檢查未通過。")
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND type IN ('table', 'view', 'trigger')"
    ).fetchall()
    object_types = {name: kind for kind, name, _ in objects}
    if set(REQUIRED_COLUMNS) - {name for name, kind in object_types.items() if kind == "table"}:
        raise SchemaValidationError("備份檔缺少 ProjMemo 必要資料表，無法還原。")
    if any(kind in {"view", "trigger"}
           or (sql and sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE"))
           for kind, _, sql in objects):
        raise SchemaValidationError("備份檔包含不支援的資料庫物件，為安全起見無法還原。")
    vault_tables = set(VAULT_COLUMNS) & set(object_types)
    if ((vault_tables and vault_tables != set(VAULT_COLUMNS))
            or (version >= 1 and vault_tables != set(VAULT_COLUMNS))):
        raise SchemaValidationError("備份檔的保管庫資料表不完整，無法還原。")
    tables = {**REQUIRED_COLUMNS, **(VAULT_COLUMNS if vault_tables else {})}
    lifecycle_columns = {"archived_at", "deleted_at", "revision"}
    if version >= 4:
        tables["projects"] = tables["projects"] | lifecycle_columns
    if version >= 2:
        if object_types.get("schema_migrations") != "table":
            raise SchemaValidationError("資料庫的遷移紀錄不完整或不相容。")
        tables["schema_migrations"] = {"version", "name", "applied_at"}
    elif "schema_migrations" in object_types:
        raise SchemaValidationError("資料庫版本與遷移紀錄不一致。")
    if version < 4 and lifecycle_columns & {row[1] for row in connection.execute('PRAGMA table_info("projects")')}:
        raise SchemaValidationError("資料庫版本與專案生命週期欄位不一致。")
    for table, required_columns in tables.items():
        columns = {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not required_columns <= columns.keys():
            raise SchemaValidationError(f"備份檔的「{table}」資料表欄位不完整，無法還原。")
        for name in required_columns:
            column = columns[name]
            expected_type = ("INTEGER" if name in INTEGER_COLUMNS else
                             "BLOB" if name in BLOB_COLUMNS else "TEXT")
            primary_key = name == ("version" if table == "schema_migrations" else "id")
            nullable = primary_key or name in {"secret_ciphertext", "secret_nonce"}
            if (column[2].upper() != expected_type
                    or primary_key and column[5] != 1
                    or not nullable and column[3] != 1):
                raise SchemaValidationError("備份檔的資料表結構不相容，無法還原。")
            condition = f'typeof("{name}") != ?'
            if nullable:
                condition += f' AND "{name}" IS NOT NULL'
            if connection.execute(
                f'SELECT 1 FROM "{table}" WHERE {condition} LIMIT 1', (expected_type.lower(),),
            ).fetchone():
                raise SchemaValidationError("備份檔含有格式錯誤的資料，無法還原。")
        if "project_id" in required_columns:
            foreign_keys = connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
            if not any(row[2] == "projects" and row[3] == "project_id"
                       and row[4] == "id" and row[6].upper() == "CASCADE" for row in foreign_keys):
                raise SchemaValidationError("備份檔的資料表結構不相容，無法還原。")
            if connection.execute(
                f'SELECT 1 FROM "{table}" AS child LEFT JOIN projects AS parent '
                'ON child.project_id = parent.id WHERE parent.id IS NULL LIMIT 1'
            ).fetchone():
                raise SchemaValidationError("備份檔含有不一致的關聯資料，無法還原。")
    for table, name in (("checklist_items", "completed"), ("environment_variables", "is_secret")):
        if connection.execute(f'SELECT 1 FROM "{table}" WHERE "{name}" NOT IN (0, 1) LIMIT 1').fetchone():
            raise SchemaValidationError("備份檔含有格式錯誤的資料，無法還原。")
    if vault_tables:
        _validate_vault_data(connection)
    if version >= 4 and connection.execute(
        "SELECT 1 FROM projects WHERE revision < 0 "
        "OR (archived_at != '' AND datetime(archived_at) IS NULL) "
        "OR (deleted_at != '' AND datetime(deleted_at) IS NULL) LIMIT 1"
    ).fetchone():
        raise SchemaValidationError("專案生命週期資料格式錯誤。")
    if version >= 2:
        expected = [(step.version, step.name) for step in MIGRATIONS if 2 <= step.version <= version]
        actual = [tuple(row) for row in connection.execute("SELECT version, name FROM schema_migrations ORDER BY version")]
        if actual != expected or connection.execute(
            "SELECT 1 FROM schema_migrations WHERE datetime(applied_at) IS NULL LIMIT 1"
        ).fetchone():
            raise SchemaValidationError("資料庫的遷移紀錄不完整或不相容。")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise SchemaValidationError("備份檔含有不一致的關聯資料，無法還原。")
    if version >= 3:
        for statement in QUERY_INDEXES + (LIFECYCLE_INDEXES if version >= 4 else ()):
            name = statement.split()[2]
            index = connection.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
            if index is None or _index_tokens(index[0]) != _index_tokens(statement):
                raise SchemaValidationError("資料庫的查詢索引不完整或不相容。")
    return version


def _index_tokens(statement: str) -> list[str]:
    # Ignore formatting/keyword case, but not the case or whitespace of values
    # inside SQL string literals (the CASE ordering must remain exact).
    return [token if token.startswith("'") else token.casefold() for token in
            re.findall(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|\d+|[^\s;]", statement)]


def _validate_vault_data(connection: sqlite3.Connection) -> None:
    configs = connection.execute("SELECT * FROM vault_config").fetchall()
    if len(configs) > 1 or configs and configs[0]["id"] != 1:
        raise SchemaValidationError("備份檔的保管庫設定不完整或不相容，無法還原。")
    if configs:
        try:
            validate_vault_metadata(configs[0])
        except VaultError as error:
            raise SchemaValidationError(str(error)) from error
    settings = connection.execute("SELECT * FROM app_settings").fetchall()
    if (len(settings) != 1 or settings[0]["id"] != 1
            or settings[0]["allow_secret_export"] not in (0, 1)
            or settings[0]["allow_secret_export"] and not configs):
        raise SchemaValidationError("備份檔的匯出設定不相容，無法還原。")
    for row in connection.execute("SELECT secret_ciphertext, secret_nonce FROM access_accounts"):
        ciphertext, nonce = row
        if ciphertext is None and nonce is None:
            continue
        if (not configs or not isinstance(ciphertext, bytes) or not 16 <= len(ciphertext) <= 16400
                or not isinstance(nonce, bytes) or len(nonce) != 12):
            raise SchemaValidationError("備份檔的加密密碼資料不完整，無法還原。")
