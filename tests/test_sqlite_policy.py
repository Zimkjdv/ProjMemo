"""Real SQLite lock conflicts, bounded backup waits and rollback guarantees."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import ast
import inspect
import sqlite3
import threading
from time import perf_counter

import pytest

from app import db, sqlite_policy
from app.database_access import DatabaseBusyError, access_for
from app.main import create_app
from app.services import projects
from tests.client import TestClient


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "locks.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    return path


def test_connection_timeout_is_explicit_and_journal_mode_unchanged(database):
    with closing(db.connect(database)) as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_write_transaction_reserves_writer_before_running_business_logic(database):
    with db.db_session(database, write=True):
        with closing(sqlite3.connect(database, timeout=0)) as other:
            with pytest.raises(sqlite3.OperationalError) as result:
                other.execute("BEGIN IMMEDIATE")
            assert sqlite_policy.is_lock_error(result.value)


def test_all_mutating_services_explicitly_request_write_transactions():
    from app.services import accounts, content, vault
    operations = [projects.create_project, projects.update_project, vault.setup, vault.update_export_policy,
                  accounts.add_access_account, accounts.update_access_account, accounts.delete_access_account]
    operations += [value for name, value in vars(content).items()
                   if callable(value) and name.startswith(("add_", "update_", "delete_", "toggle_"))]
    for operation in operations:
        tree = ast.parse(inspect.getsource(operation))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "db_session"]
        assert calls and all(any(kw.arg == "write" and isinstance(kw.value, ast.Constant)
                                 and kw.value.value is True for kw in call.keywords) for call in calls), operation.__name__


def test_short_conflict_waits_then_commits_exactly_once(database):
    writer = sqlite3.connect(database)
    writer.execute("BEGIN IMMEDIATE")
    entered = threading.Event()
    def save():
        entered.set()
        return projects.create_project(name="one committed project")
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(save)
        try:
            assert entered.wait(2)
            assert not pending.done()
        finally:
            writer.rollback()
            writer.close()
        assert pending.result(timeout=3) == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


@pytest.mark.parametrize("language,message", [("zh-Hant", "資料庫忙碌，請稍後再試。"), ("en", "The database is busy. Please try again shortly.")])
def test_expired_writer_wait_returns_retryable_localized_503_without_inserting(database, language, message):
    with TestClient(create_app(), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        writer = sqlite3.connect(database)
        writer.execute("BEGIN IMMEDIATE")
        try:
            start = perf_counter()
            response = client.post("/projects/new", data={"name": "must not be inserted"})
            elapsed = perf_counter() - start
            assert response.status_code == 503
            assert response.json() == {"detail": message}
            assert response.headers["retry-after"] == "1"
            assert "no-store" in response.headers["cache-control"]
            assert elapsed < 3  # Generous scheduling margin, not a speed benchmark.
        finally:
            writer.rollback()
            writer.close()
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert client.post("/projects/new", data={"name": "explicit retry"}).status_code == 303


def test_commit_lock_conflict_rolls_back_all_pending_changes(database):
    reader = sqlite3.connect(database)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM projects").fetchall()
    try:
        with pytest.raises(DatabaseBusyError):
            with db.db_session(database, write=True) as connection:
                connection.execute("INSERT INTO projects(name) VALUES('must roll back')")
    finally:
        reader.rollback()
        reader.close()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED_SHAREDCACHE])
def test_extended_busy_and_locked_codes_are_recognized(code):
    error = sqlite3.OperationalError("test-only locked error")
    error.sqlite_errorcode = code
    assert sqlite_policy.is_lock_error(error)


def test_unrelated_sql_errors_are_not_mislabeled_as_busy(database):
    with pytest.raises(sqlite3.OperationalError):
        with db.db_session(database, write=True) as connection:
            connection.execute("SELECT * FROM nonexistent_table")


def test_failed_explicit_rollback_marks_database_unavailable(database, monkeypatch):
    class BrokenRollback(sqlite3.Connection):
        def rollback(self):
            raise sqlite3.OperationalError("test-only rollback failure")
    def connect(path):
        return sqlite3.connect(path, factory=BrokenRollback)
    monkeypatch.setattr(db, "connect", connect)
    with pytest.raises(DatabaseBusyError):
        with db.db_session(database, write=True):
            raise ValueError("test-only business failure")
    with pytest.raises(DatabaseBusyError):
        with access_for(database).operation():
            pytest.fail("Recovery-required database must remain blocked")


def test_backup_api_busy_loop_is_bounded_and_does_not_replace_destination(database, tmp_path, monkeypatch):
    destination = tmp_path / "locked-destination.db"
    db.init_db(destination)
    writer = sqlite3.connect(destination)
    writer.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(sqlite_policy, "SQLITE_LOCK_WAIT_SECONDS", .05)
    try:
        start = perf_counter()
        with pytest.raises(DatabaseBusyError):
            sqlite_policy.copy_database(database, destination)
        assert perf_counter() - start < 1
    finally:
        writer.rollback()
        writer.close()
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


def test_healthy_backup_has_no_total_copy_deadline(database, tmp_path, monkeypatch):
    # A zero lock-wait budget must not prevent a healthy copy.
    monkeypatch.setattr(sqlite_policy, "SQLITE_LOCK_WAIT_SECONDS", 0)
    destination = tmp_path / "healthy-copy.db"
    sqlite_policy.copy_database(database, destination)
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED_SHAREDCACHE])
def test_backup_progress_bounds_basic_and_extended_lock_statuses(tmp_path, monkeypatch, code):
    closed = []
    class Connection:
        def backup(self, destination, *, pages, progress, sleep):
            progress(code, 1, 1)
            progress(code, 1, 1)

        def close(self):
            closed.append(self)
    times = iter([0, 2])
    monkeypatch.setattr(sqlite_policy.sqlite3, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(sqlite_policy, "monotonic", lambda: next(times))
    with pytest.raises(DatabaseBusyError):
        sqlite_policy.copy_database(tmp_path / "source.db", tmp_path / "target.db")
    assert len(closed) == 2


def test_read_sessions_keep_a_consistent_multi_query_snapshot(database):
    # WAL is only a test fixture proving snapshot semantics, not an app setting.
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    with db.db_session(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        with closing(sqlite3.connect(database)) as writer, writer:
            writer.execute("INSERT INTO projects(name) VALUES('new committed row')")
        assert reader.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    with db.db_session(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
