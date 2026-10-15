"""SQLite sessions and fail-safe, versioned startup migrations for ProjMemo."""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator

from .database_access import DatabaseBusyError, access_for
from .migrations import MIGRATIONS, SCHEMA_VERSION
from .schema_validation import validate_schema
from .sqlite_policy import (
    DATABASE_BUSY_MESSAGE, SQLITE_LOCK_WAIT_SECONDS, copy_database as _copy_database, is_lock_error,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "projmemo.db"
logger = logging.getLogger(__name__)


class MigrationError(sqlite3.DatabaseError):
    """Startup must stop; a retained snapshot identifies the recovery point."""

    def __init__(self, message: str, *, snapshot_path: Path | None = None, recovered: bool = True):
        super().__init__(message)
        self.snapshot_path = snapshot_path
        self.recovered = recovered


def database_path() -> Path:
    """Return the configured database path and create its parent directory."""
    configured_path = os.getenv("PROJMEMO_DB_PATH")
    path = Path(configured_path) if configured_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path or database_path(), timeout=SQLITE_LOCK_WAIT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def db_session(path: Path | None = None, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    path = path or database_path()
    access = access_for(path)
    with access.operation():
        connection = None
        try:
            connection = connect(path)
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception as error:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error as rollback_error:
                    access.require_recovery()
                    raise DatabaseBusyError("資料庫需要復原，請保留備份並停止程式後復原。") from rollback_error
            if is_lock_error(error):
                raise DatabaseBusyError(DATABASE_BUSY_MESSAGE) from error
            raise
        finally:
            if connection is not None:
                connection.close()


def _validate_file(path: Path) -> int:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True,
                                 timeout=SQLITE_LOCK_WAIT_SECONDS)
    connection.row_factory = sqlite3.Row
    try:
        return validate_schema(connection)
    finally:
        connection.close()


def _create_migration_snapshot(path: Path, version: int) -> Path:
    directory = path.parent / "backups" / "migrations"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    descriptor, filename = tempfile.mkstemp(
        prefix=f"projmemo-pre-migration-v{version}-to-v{SCHEMA_VERSION}-{timestamp}-",
        suffix=".sqlite3", dir=directory,
    )
    os.close(descriptor)
    snapshot = Path(filename)
    try:
        _copy_database(path, snapshot)
        if _validate_file(snapshot) != version:
            raise MigrationError("Migration snapshot version changed unexpectedly")
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    return snapshot


def _migration_authorizer(action, first, second, database, source):
    # Guard the one atomic upgrade transaction against accidental commit(),
    # executescript(), savepoints, or attached/external databases in callbacks.
    if action in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
                  sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def init_db(path: Path | None = None) -> None:
    """Apply missing versions once, atomically, retaining an upgrade snapshot.

    Existing v0 databases must match the shipped five- or eight-table schema;
    v1 is the former eight-table schema. History starts at v2, not retroactively.
    """
    path = Path(path or database_path()).resolve()
    if [step.version for step in MIGRATIONS] != list(range(1, SCHEMA_VERSION + 1)):
        raise MigrationError("Migration registry must contain every version in order")
    path.parent.mkdir(parents=True, exist_ok=True)
    access = access_for(path)
    with access.maintenance(reuse=True):
        connection = connect(path)
        snapshot = None
        started = False
        try:
            # Reserve the writer before validation/snapshot. A separate backup
            # reader still sees the unchanged committed database (also in WAL).
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            objects = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            fresh = version == 0 and not objects
            if not fresh:
                validate_schema(connection)
            if version == SCHEMA_VERSION:
                connection.commit()
                return
            if not fresh:
                snapshot = _create_migration_snapshot(path, version)
                logger.info("Schema upgrade v%s -> v%s; recovery snapshot: %s", version, SCHEMA_VERSION, snapshot)
            started = True
            connection.set_authorizer(_migration_authorizer)
            for step in MIGRATIONS:
                if step.version <= version:
                    continue
                step.apply(connection)
                if step.version >= 2:
                    connection.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                                       (step.version, step.name))
                connection.execute(f"PRAGMA user_version = {step.version}")
            validate_schema(connection)
            connection.set_authorizer(None)
            connection.commit()
            logger.info("Schema ready at v%s", SCHEMA_VERSION)
        except Exception as error:
            # Closing also rolls back if the explicit rollback itself fails.
            try:
                connection.set_authorizer(None)
                connection.rollback()
            except sqlite3.Error:
                logger.error("Migration rollback failed; closing the connection before recovery")
            finally:
                connection.close()
            if snapshot is not None and started:
                try:
                    _copy_database(snapshot, path)
                    if _validate_file(path) != version:
                        raise MigrationError("Recovered database has an unexpected version")
                except Exception as recovery_error:
                    access.require_recovery()
                    raise MigrationError(
                        f"Schema upgrade failed; automatic recovery failed. Stop ProjMemo and recover from: {snapshot}",
                        snapshot_path=snapshot, recovered=False,
                    ) from recovery_error
                raise MigrationError(
                    f"Schema upgrade failed; original database restored. Recovery snapshot: {snapshot}",
                    snapshot_path=snapshot,
                ) from error
            raise MigrationError("Schema initialization/validation failed; no upgrade was committed.") from error
        finally:
            connection.close()
