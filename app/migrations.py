"""Append-only SQLite migrations. Callbacks must not manage transactions."""

from dataclasses import dataclass
import sqlite3
from typing import Callable


SCHEMA_VERSION = 3


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


# v1 describes the already shipped eight-table schema. It also adopts the
# unversioned five-table release, adding only the three missing vault tables.
BASELINE_TABLES = (
    ("projects", """CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'maintenance',
        owner TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""),
    ("project_urls", """CREATE TABLE project_urls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'other',
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )"""),
    ("notes", """CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'note',
        title TEXT NOT NULL,
        content_markdown TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'normal',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )"""),
    ("checklist_items", """CREATE TABLE checklist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'other',
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        owner TEXT NOT NULL DEFAULT '',
        completed INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )"""),
    ("environment_variables", """CREATE TABLE environment_variables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        environment TEXT NOT NULL DEFAULT 'local',
        description TEXT NOT NULL DEFAULT '',
        source_or_owner TEXT NOT NULL DEFAULT '',
        is_secret INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )"""),
    ("access_accounts", """CREATE TABLE access_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'website',
        environment TEXT NOT NULL DEFAULT 'test',
        endpoint TEXT NOT NULL DEFAULT '',
        database_name TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '',
        role_scope TEXT NOT NULL DEFAULT '',
        purpose TEXT NOT NULL DEFAULT '',
        owner TEXT NOT NULL DEFAULT '',
        secret_reference TEXT NOT NULL DEFAULT '',
        secret_ciphertext BLOB,
        secret_nonce BLOB,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )"""),
    ("vault_config", """CREATE TABLE vault_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        salt BLOB NOT NULL,
        verifier_nonce BLOB NOT NULL,
        verifier_ciphertext BLOB NOT NULL,
        kdf_memory_cost INTEGER NOT NULL,
        kdf_iterations INTEGER NOT NULL,
        kdf_lanes INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""),
    ("app_settings", """CREATE TABLE app_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        allow_secret_export INTEGER NOT NULL DEFAULT 0
    )"""),
)


def baseline_schema(connection: sqlite3.Connection) -> None:
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for name, statement in BASELINE_TABLES:
        if name not in existing:
            connection.execute(statement)
    connection.execute("INSERT OR IGNORE INTO app_settings (id, allow_secret_export) VALUES (1, 0)")


def migration_history(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


QUERY_INDEXES = (
    "CREATE INDEX idx_projects_updated ON projects(updated_at DESC, id DESC)",
    "CREATE INDEX idx_projects_status_updated ON projects(status, updated_at DESC, id DESC)",
    "CREATE INDEX idx_urls_project_order ON project_urls(project_id, id DESC)",
    "CREATE INDEX idx_notes_project_order ON notes(project_id, id DESC)",
    "CREATE INDEX idx_checklist_project_order ON checklist_items(project_id, completed, id DESC)",
    """CREATE INDEX idx_environment_project_order ON environment_variables(
        project_id, CASE environment WHEN 'local' THEN 1 WHEN 'staging' THEN 2
        WHEN 'production' THEN 3 ELSE 4 END, key COLLATE NOCASE)""",
    """CREATE INDEX idx_accounts_project_order ON access_accounts(
        project_id, CASE environment WHEN 'production' THEN 1 WHEN 'staging' THEN 2 ELSE 3 END,
        label COLLATE NOCASE)""",
)


def query_indexes(connection: sqlite3.Connection) -> None:
    """v3: measured project filtering/order paths; never rewrite business rows."""
    for statement in QUERY_INDEXES:
        connection.execute(statement)


MIGRATIONS = (
    Migration(1, "baseline_schema", baseline_schema),
    Migration(2, "migration_history", migration_history),
    Migration(3, "query_indexes", query_indexes),
)
