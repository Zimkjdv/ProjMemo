"""Migration tests never open the user's configured or default database."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
import threading

import pytest

from app import db
from app.backup import BackupRestoreError, BackupValidationError, restore_database, validate_backup
from app.database_access import DatabaseBusyError, access_for
from app.migrations import BASELINE_TABLES, baseline_schema
from app.vault import create_vault, decrypt_secret, encrypt_secret, unlock_vault


def legacy_database(path, version=1, vault=True):
    """Reproduce the shipped v1 DDL without running the new migration runner."""
    with sqlite3.connect(path) as connection:
        baseline_schema(connection)
        connection.execute("INSERT INTO projects (id, name, owner, tags) VALUES (7, '原專案 / Old project', 'Owner', 'Python, API')")
        connection.execute("INSERT INTO project_urls (project_id, title, url) VALUES (7, 'Repository', 'https://example.invalid/repo')")
        connection.execute("INSERT INTO notes (project_id, title, content_markdown) VALUES (7, '備註', '**keep** `code`')")
        connection.execute("INSERT INTO checklist_items (project_id, title, completed) VALUES (7, 'Transfer', 1)")
        connection.execute("INSERT INTO environment_variables (project_id, key, is_secret) VALUES (7, 'TEST_KEY', 1)")
        if not vault:
            for table in ("access_accounts", "vault_config", "app_settings"):
                connection.execute(f"DROP TABLE {table}")
        connection.execute(f"PRAGMA user_version = {version}")
    return path


def logical_state(path):
    connection = sqlite3.connect(path)
    try:
        return (connection.execute("PRAGMA user_version").fetchone()[0], tuple(connection.iterdump()))
    finally:
        connection.close()


def snapshots(path):
    return list((path.parent / "backups" / "migrations").glob("*.sqlite3"))


def patch_step(monkeypatch, version, callback):
    monkeypatch.setattr(db, "MIGRATIONS", tuple(
        replace(step, apply=callback) if step.version == version else step for step in db.MIGRATIONS
    ))


def test_fresh_database_runs_versions_in_order_without_empty_backup(tmp_path, monkeypatch):
    path = tmp_path / "new" / "fresh.db"
    calls = []
    for step in db.MIGRATIONS:
        def observe(connection, step=step):
            calls.append((step.version, connection.execute("PRAGMA user_version").fetchone()[0]))
            step.apply(connection)
        patch_step(monkeypatch, step.version, observe)
    db.init_db(path)
    assert calls == [(1, 0), (2, 1)]
    assert not (path.parent / "backups").exists()
    validate_backup(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 2
        assert connection.execute("SELECT version, name FROM schema_migrations").fetchall() == [(2, "migration_history")]
        assert connection.execute("SELECT allow_secret_export FROM app_settings").fetchone() == (0,)
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            *(name for name, _ in BASELINE_TABLES), "schema_migrations", "sqlite_sequence",
        }


@pytest.mark.parametrize("version,vault", [(0, False), (0, True), (1, True)])
def test_legacy_upgrade_preserves_all_data_and_snapshot_is_pre_upgrade(tmp_path, version, vault):
    path = legacy_database(tmp_path / "old.db", version, vault)
    before = logical_state(path)
    db.init_db(path)
    validate_backup(path)
    saved, = snapshots(path)
    assert logical_state(saved) == before
    assert f"v{version}-to-v2-" in saved.name
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id, name FROM projects").fetchone() == (7, '原專案 / Old project')
        assert connection.execute("SELECT content_markdown FROM notes").fetchone() == ('**keep** `code`',)
        assert connection.execute("SELECT completed FROM checklist_items").fetchone() == (1,)
        assert connection.execute("SELECT is_secret FROM environment_variables").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM project_urls").fetchone() == (1,)
        connection.execute("INSERT INTO projects (name) VALUES ('Next')")
        assert connection.execute("SELECT id FROM projects WHERE name='Next'").fetchone() == (8,)


def test_vault_ciphertext_ids_settings_and_original_master_password_survive(tmp_path):
    path = legacy_database(tmp_path / "vault.db")
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        key = create_vault(connection, "test-only-master-password")
        ciphertext, nonce = encrypt_secret(key, 7, 11, "test-only-secret")
        connection.execute("INSERT INTO access_accounts (id, project_id, label, secret_ciphertext, secret_nonce) VALUES (11, 7, 'DB', ?, ?)", (ciphertext, nonce))
        connection.execute("UPDATE app_settings SET allow_secret_export=1")
        config = tuple(connection.execute("SELECT * FROM vault_config").fetchone())
    db.init_db(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        assert tuple(connection.execute("SELECT * FROM vault_config").fetchone()) == config
        key = unlock_vault(connection, "test-only-master-password")
        row = connection.execute("SELECT * FROM access_accounts").fetchone()
        assert (row["id"], row["project_id"], row["secret_ciphertext"], row["secret_nonce"]) == (11, 7, ciphertext, nonce)
        assert decrypt_secret(key, 7, 11, row["secret_ciphertext"], row["secret_nonce"]) == "test-only-secret"
        assert connection.execute("SELECT allow_secret_export FROM app_settings").fetchone()[0] == 1


def test_restart_is_byte_identical_without_repeating_migrations_or_backups(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "repeat.db")
    db.init_db(path)
    before = path.read_bytes()
    saved = snapshots(path)
    def forbidden(connection):
        pytest.fail("A completed migration must never run again")
    for step in db.MIGRATIONS:
        patch_step(monkeypatch, step.version, forbidden)
    db.init_db(path)
    db.init_db(path)
    assert path.read_bytes() == before
    assert snapshots(path) == saved


@pytest.mark.parametrize("mutation", [
    "PRAGMA user_version=99", "PRAGMA user_version=-1", "DROP TABLE vault_config",
    "ALTER TABLE notes DROP COLUMN priority", "UPDATE project_urls SET project_id=999",
    "CREATE TRIGGER unexpected AFTER INSERT ON projects BEGIN DELETE FROM notes; END",
    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)",
])
def test_unknown_or_invalid_existing_schema_is_never_repaired_or_overwritten(tmp_path, mutation):
    path = legacy_database(tmp_path / "invalid.db")
    with sqlite3.connect(path) as connection:
        connection.execute(mutation)
    before = path.read_bytes()
    with pytest.raises(db.MigrationError):
        db.init_db(path)
    assert path.read_bytes() == before
    assert not snapshots(path)


@pytest.mark.parametrize("mutation", [
    "DROP TABLE schema_migrations", "DELETE FROM schema_migrations",
    "UPDATE schema_migrations SET name='unexpected'", "UPDATE schema_migrations SET applied_at=''",
    "UPDATE schema_migrations SET version=3", "PRAGMA user_version=1",
])
def test_current_version_requires_matching_valid_history_for_startup_and_restore(tmp_path, mutation):
    path = tmp_path / "invalid-history.db"
    db.init_db(path)
    with sqlite3.connect(path) as connection:
        connection.execute(mutation)
    before = path.read_bytes()
    with pytest.raises(BackupValidationError):
        validate_backup(path)
    with pytest.raises(db.MigrationError):
        db.init_db(path)
    assert path.read_bytes() == before
    assert not snapshots(path)


@pytest.mark.parametrize("kind", ["missing", "unordered", "duplicate"])
def test_invalid_registry_fails_before_creating_database(tmp_path, monkeypatch, kind):
    steps = db.MIGRATIONS
    invalid = {"missing": steps[1:], "unordered": steps[::-1], "duplicate": steps + steps[-1:]}[kind]
    monkeypatch.setattr(db, "MIGRATIONS", invalid)
    path = tmp_path / "untouched.db"
    with pytest.raises(db.MigrationError, match="registry"):
        db.init_db(path)
    assert not path.exists()


def test_snapshot_failure_aborts_before_any_ddl_and_removes_partial_copy(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "snapshot-fail.db")
    before = path.read_bytes()
    def failed_copy(source, destination):
        connection = sqlite3.connect(destination)
        try:
            connection.execute("CREATE TABLE partial (id INTEGER)")
        finally:
            connection.close()
        raise OSError("test-only full disk")
    monkeypatch.setattr(db, "_copy_database", failed_copy)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.snapshot_path is None
    assert path.read_bytes() == before
    assert snapshots(path) == []


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_second_step_failure_restores_all_versions_and_retry_runs_once(tmp_path, monkeypatch, journal):
    path = legacy_database(tmp_path / "failure.db", version=0, vault=False)
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"PRAGMA journal_mode={journal}")
    finally:
        connection.close()
    before = logical_state(path)
    original = db.MIGRATIONS
    def fail(connection):
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        connection.execute("ALTER TABLE projects ADD COLUMN should_disappear TEXT")
        connection.execute("UPDATE projects SET name='must disappear'")
        connection.execute("CREATE TABLE transient (id INTEGER)")
        raise sqlite3.OperationalError("test-only migration failure")
    patch_step(monkeypatch, 2, fail)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert result.value.snapshot_path in snapshots(path)
    assert logical_state(path) == before
    assert logical_state(result.value.snapshot_path) == before
    monkeypatch.setattr(db, "MIGRATIONS", original)
    db.init_db(path)
    db.init_db(path)
    validate_backup(path)
    assert len(snapshots(path)) == 2  # Failed attempt and successful retry only.


@pytest.mark.parametrize("transaction", ["commit", "executescript", "savepoint", "attach"])
def test_migration_cannot_escape_atomic_transaction(tmp_path, monkeypatch, transaction):
    path = legacy_database(tmp_path / "atomic.db")
    before = logical_state(path)
    def incorrect_callback(connection):
        connection.execute("UPDATE projects SET name='partial'")
        if transaction == "commit":
            connection.commit()
        elif transaction == "executescript":
            connection.executescript("CREATE TABLE partial (id INTEGER);")
        elif transaction == "savepoint":
            connection.execute("SAVEPOINT partial")
        else:
            connection.execute("ATTACH DATABASE ':memory:' AS other")
    patch_step(monkeypatch, 2, incorrect_callback)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert logical_state(path) == before


def test_fresh_failure_rolls_back_ddl_and_can_restart(tmp_path, monkeypatch):
    path = tmp_path / "fresh-failure.db"
    original = db.MIGRATIONS
    def fail(connection):
        raise sqlite3.OperationalError("test-only failure")
    patch_step(monkeypatch, 2, fail)
    with pytest.raises(db.MigrationError):
        db.init_db(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    assert not snapshots(path)
    monkeypatch.setattr(db, "MIGRATIONS", original)
    db.init_db(path)
    validate_backup(path)


@pytest.mark.parametrize("rollback_error", [False, True])
def test_commit_failure_recovers_snapshot_even_if_explicit_rollback_fails(tmp_path, monkeypatch, rollback_error):
    path = legacy_database(tmp_path / "commit-fail.db")
    before = logical_state(path)
    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("test-only commit failure")

        def rollback(self):
            if rollback_error:
                raise sqlite3.OperationalError("test-only rollback failure")
            super().rollback()

    def failing_connection(path):
        connection = sqlite3.connect(path, factory=FailedCommit)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    monkeypatch.setattr(db, "connect", failing_connection)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert logical_state(path) == before
    assert logical_state(result.value.snapshot_path) == before


def test_post_migration_validation_failure_restores_original(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "post-check-fail.db")
    before = logical_state(path)
    original = db.MIGRATIONS[-1].apply
    def incorrect_migration(connection):
        original(connection)
        connection.execute("UPDATE app_settings SET allow_secret_export=99")
    patch_step(monkeypatch, 2, incorrect_migration)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert logical_state(path) == before


def test_future_migration_only_applies_missing_version(tmp_path, monkeypatch):
    from app import migrations, schema_validation
    path = tmp_path / "future.db"
    db.init_db(path)
    calls = []
    def upgrade(connection):
        calls.append(3)
        connection.execute("ALTER TABLE projects ADD COLUMN fixture_only TEXT NOT NULL DEFAULT ''")
    steps = (*db.MIGRATIONS, migrations.Migration(3, "test_only_future_schema", upgrade))
    for module in (db, migrations, schema_validation):
        monkeypatch.setattr(module, "SCHEMA_VERSION", 3)
        monkeypatch.setattr(module, "MIGRATIONS", steps)
    db.init_db(path)
    db.init_db(path)
    assert calls == [3]
    saved, = snapshots(path)
    with sqlite3.connect(saved) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(2,), (3,)]
    validate_backup(path)


def test_failed_automatic_recovery_keeps_snapshot_and_blocks_database(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "recovery-failure.db")
    before = logical_state(path)
    def fail(connection):
        raise sqlite3.OperationalError("test-only migration failure")
    patch_step(monkeypatch, 2, fail)
    original_copy = db._copy_database
    def fail_recovery(source, destination):
        if source.parent.name == "migrations":
            raise OSError("test-only recovery disk error")
        original_copy(source, destination)
    monkeypatch.setattr(db, "_copy_database", fail_recovery)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert not result.value.recovered
    assert logical_state(result.value.snapshot_path) == before
    assert str(result.value.snapshot_path) in str(result.value)
    with pytest.raises(DatabaseBusyError):
        with db.db_session(path):
            pytest.fail("Recovery-required database must remain blocked")


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_snapshot_contains_committed_writes_including_wal(tmp_path, journal):
    path = legacy_database(tmp_path / "journal.db")
    writer = sqlite3.connect(path)
    try:
        assert writer.execute(f"PRAGMA journal_mode={journal}").fetchone()[0] == journal
        writer.execute("UPDATE projects SET name='committed before upgrade'")
        writer.commit()
        if journal == "wal":
            assert path.with_name(path.name + "-wal").exists()
        db.init_db(path)
        saved, = snapshots(path)
        with sqlite3.connect(saved) as connection:
            assert connection.execute("SELECT name FROM projects").fetchone() == ('committed before upgrade',)
    finally:
        writer.close()


def test_upgrade_waits_for_admitted_transaction_and_excludes_other_operations(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "concurrent.db")
    access = access_for(path)
    started, release = threading.Event(), threading.Event()
    original = db.MIGRATIONS[-1].apply
    def paused(connection):
        started.set()
        assert release.wait(5)
        original(connection)
    patch_step(monkeypatch, 2, paused)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with db.db_session(path) as connection:
            connection.execute("UPDATE projects SET name='last admitted write'")
            upgrading = workers.submit(db.init_db, path)
            with access._condition:
                assert access._condition.wait_for(lambda: access._restoring, timeout=5)
            assert not snapshots(path)
        try:
            assert started.wait(5)
            with pytest.raises(DatabaseBusyError):
                db.init_db(path)
            with pytest.raises(DatabaseBusyError):
                with db.db_session(path):
                    pytest.fail("Migration must exclude new requests")
        finally:
            release.set()
        upgrading.result(timeout=5)
    saved, = snapshots(path)
    with sqlite3.connect(saved) as connection:
        assert connection.execute("SELECT name FROM projects").fetchone() == ('last admitted write',)


def test_normal_operation_cannot_reuse_maintenance_lease(tmp_path):
    path = tmp_path / "no-deadlock.db"
    db.init_db(path)
    with db.db_session(path):
        with pytest.raises(DatabaseBusyError):
            db.init_db(path)


@pytest.mark.parametrize("version,vault", [(0, False), (0, True), (1, True)])
def test_old_backup_restores_then_migrates_under_same_exclusive_lease(tmp_path, version, vault):
    old = legacy_database(tmp_path / "old-backup.db", version, vault)
    before = old.read_bytes()
    current = tmp_path / "current.db"
    db.init_db(current)
    recovery = restore_database(old, current)
    assert old.read_bytes() == before  # Upload validation never mutates the input.
    validate_backup(current)
    validate_backup(recovery)
    assert logical_state(snapshots(current)[0]) == logical_state(old)
    with sqlite3.connect(current) as connection:
        assert connection.execute("SELECT id FROM projects").fetchone() == (7,)


def test_old_backup_failed_migration_restores_pre_restore_database(tmp_path, monkeypatch):
    old = legacy_database(tmp_path / "old-backup.db")
    current = tmp_path / "current.db"
    db.init_db(current)
    before = logical_state(current)
    def fail(connection):
        raise sqlite3.OperationalError("test-only migration failure")
    patch_step(monkeypatch, 2, fail)
    with pytest.raises(BackupRestoreError) as result:
        restore_database(old, current)
    assert result.value.recovered
    assert logical_state(current) == before


def test_lifespan_refuses_to_serve_after_migration_failure(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "startup-fail.db")
    before = logical_state(path)
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    from tests.client import TestClient
    from app.main import app
    def fail(connection):
        raise sqlite3.OperationalError("test-only migration failure")
    patch_step(monkeypatch, 2, fail)
    with pytest.raises(db.MigrationError):
        with TestClient(app):
            pytest.fail("Startup must fail, not serve a partially migrated database")
    assert logical_state(path) == before


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_legacy_startup_serves_original_project_and_markdown_after_upgrade(tmp_path, monkeypatch, language):
    path = legacy_database(tmp_path / "startup-success.db")
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    from tests.client import TestClient
    from app.main import app
    with TestClient(app) as client:
        client.cookies.set("projmemo_language", language)
        response = client.get("/projects/7")
        assert response.status_code == 200
        assert '原專案 / Old project' in response.text
        exported = client.get("/projects/7/export.md")
        assert exported.status_code == 200
        assert '**keep** `code`' in exported.text
    assert len(snapshots(path)) == 1


@pytest.mark.parametrize("mutation,expected", [
    ("DELETE FROM schema_migrations", "The database migration history is incomplete or incompatible."),
    ("PRAGMA user_version=1", "The database version does not match its migration history."),
])
def test_restore_history_errors_are_translated_without_touching_current_database(tmp_path, monkeypatch, mutation, expected):
    incoming = tmp_path / "invalid-upload.db"
    db.init_db(incoming)
    with sqlite3.connect(incoming) as connection:
        connection.execute(mutation)
    current = tmp_path / "current.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    from tests.client import TestClient
    from app.main import app
    with TestClient(app) as client:
        client.cookies.set("projmemo_language", "en")
        before = current.read_bytes()
        response = client.post("/settings/backup/restore", files={"backup_file": ("invalid.sqlite3", incoming.read_bytes())})
        assert response.status_code == 400
        assert expected in response.text
        assert current.read_bytes() == before


def test_other_sqlite_writer_aborts_before_snapshot_or_ddl(tmp_path, monkeypatch):
    path = legacy_database(tmp_path / "external-writer.db")
    before = logical_state(path)
    original_connect = db.connect
    def short_timeout(path):
        connection = original_connect(path)
        connection.execute("PRAGMA busy_timeout=1")
        return connection
    monkeypatch.setattr(db, "connect", short_timeout)
    writer = sqlite3.connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(db.MigrationError):
            db.init_db(path)
        assert not snapshots(path)
    finally:
        writer.close()
    assert logical_state(path) == before
