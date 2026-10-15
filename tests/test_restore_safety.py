from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

from tests.client import TestClient
import pytest

from app import backup as backups
from app.database_access import access_for, DatabaseBusyError
from app.db import init_db, db_session


@pytest.fixture
def databases(tmp_path, monkeypatch):
    current, incoming = tmp_path / "current.sqlite3", tmp_path / "incoming.sqlite3"
    for path, name in ((current, "keep original"), (incoming, "replacement")):
        init_db(path)
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    return current, incoming


def project_name(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT name FROM projects").fetchone()[0]


def test_initialization_failure_recovers_original_and_keeps_downloadable_snapshot(databases, monkeypatch):
    current, incoming = databases
    from app.main import app
    vault_sessions = app.state.runtime.vault_sessions
    with TestClient(app, follow_redirects=False) as client:
        token = vault_sessions.issue(b"x" * 32)
        def fail_after_replacement(path):
            assert project_name(path) == "replacement"
            raise sqlite3.DatabaseError("simulated initialization failure")
        monkeypatch.setattr("app.services.backups.init_db", fail_after_replacement)
        response = client.post("/settings/backup/restore", files={"backup_file": ("incoming.sqlite3", incoming.read_bytes())})
        assert response.status_code == 500
        assert "已使用還原前備份回復" in response.text
        assert project_name(current) == "keep original"
        assert vault_sessions.get_key(token) is None
        snapshot = next((current.parent / "backups").glob("*.sqlite3"))
        assert project_name(snapshot) == "keep original"
        assert client.get(f"/settings/backup/files/{snapshot.name}").status_code == 200
        assert "keep original" in client.get("/").text


def test_copy_failure_is_recovered(databases, monkeypatch):
    current, incoming = databases
    copy = backups._copy_database
    def broken_copy(source, target):
        if source == incoming:
            copy(source, target)
            raise sqlite3.DatabaseError("simulated partial copy failure")
        copy(source, target)
    monkeypatch.setattr(backups, "_copy_database", broken_copy)
    with pytest.raises(backups.BackupRestoreError) as result:
        backups.restore_database(incoming, current)
    assert result.value.recovered
    assert project_name(current) == "keep original"
    with db_session(current) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_failed_rollback_blocks_data_access_but_keeps_recovery_download(databases, monkeypatch):
    current, incoming = databases
    from app.main import app
    copy = backups._copy_database
    with TestClient(app, follow_redirects=False) as client:
        def broken_copy(source, target):
            if source.name.startswith(".projmemo-upload-") or source.parent.name == "backups":
                raise sqlite3.DatabaseError("simulated disk failure")
            copy(source, target)
        monkeypatch.setattr(backups, "_copy_database", broken_copy)
        response = client.post("/settings/backup/restore", files={"backup_file": ("incoming.sqlite3", incoming.read_bytes())})
        assert response.status_code == 500
        assert "自動回復未能完成" in response.text
        assert client.post("/projects/new", data={"name": "unsafe write"}).status_code == 503
        assert client.get("/").status_code == 503
        assert client.get("/settings/backup").status_code == 200
        snapshot = next((current.parent / "backups").glob("*.sqlite3"))
        assert client.get(f"/settings/backup/files/{snapshot.name}").status_code == 200
        assert project_name(snapshot) == "keep original"
        with pytest.raises(DatabaseBusyError):
            with db_session(current):
                pytest.fail("Blocked database must not admit a transaction")


def test_restore_excludes_new_requests_and_second_restore(databases, monkeypatch):
    current, incoming = databases
    from app.main import app
    vault_sessions = app.state.runtime.vault_sessions
    started, release = threading.Event(), threading.Event()
    with TestClient(app, follow_redirects=False) as client:
        token = vault_sessions.issue(b"x" * 32)
        def paused_initialize(path):
            started.set()
            assert release.wait(5)
            init_db(path)
        monkeypatch.setattr("app.services.backups.init_db", paused_initialize)
        with ThreadPoolExecutor(max_workers=1) as workers:
            restoring = workers.submit(client.post, "/settings/backup/restore",
                                       files={"backup_file": ("incoming.sqlite3", incoming.read_bytes())})
            try:
                assert started.wait(5)
                write = client.post("/projects/new", data={"name": "must not write"})
                assert write.status_code == 503
                assert write.headers["retry-after"] == "1"
                assert client.get("/projects/1").status_code == 503
                second = client.post("/settings/backup/restore", files={"backup_file": ("incoming.sqlite3", incoming.read_bytes())})
                assert second.status_code == 503
            finally:
                release.set()
            assert restoring.result(timeout=5).status_code == 303
        assert project_name(current) == "replacement"
        assert vault_sessions.get_key(token) is None
        assert client.post("/projects/new", data={"name": "allowed after restore"}).status_code == 303


def test_restore_waits_for_existing_transaction_before_snapshot(databases):
    current, incoming = databases
    access = access_for(current)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with db_session(current) as connection:
            connection.execute("UPDATE projects SET name = 'committed before snapshot'")
            restoring = workers.submit(backups.restore_database, incoming, current)
            with access._condition:
                assert access._condition.wait_for(lambda: access._restoring, timeout=5)
            assert not (current.parent / "backups").exists()
        snapshot = restoring.result(timeout=5)
    assert project_name(snapshot) == "committed before snapshot"
    assert project_name(current) == "replacement"


def test_snapshot_failure_leaves_original_and_does_not_clear_sessions(databases, monkeypatch):
    current, incoming = databases
    cleared = []
    def failed_snapshot(*args):
        raise OSError("simulated full disk")
    monkeypatch.setattr(backups, "create_database_backup", failed_snapshot)
    with pytest.raises(OSError):
        backups.restore_database(incoming, current, on_replace=lambda: cleared.append(True))
    assert cleared == []
    assert project_name(current) == "keep original"
    with db_session(current):
        pass


def test_post_initialization_validation_failure_is_recovered(databases):
    current, incoming = databases
    def corrupt_initialized_settings(path):
        init_db(path)
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE app_settings SET allow_secret_export = 99")
    with pytest.raises(backups.BackupRestoreError) as result:
        backups.restore_database(incoming, current, initialize=corrupt_initialized_settings)
    assert result.value.recovered
    assert project_name(current) == "keep original"
    backups.validate_backup(current)
