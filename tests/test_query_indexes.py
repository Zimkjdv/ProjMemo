"""Measured index paths, legacy v2 migration safety and complete exports."""

from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from app import db
from app.backup import BackupValidationError, restore_database, validate_backup
from app.migrations import QUERY_INDEXES, baseline_schema, migration_history
from app.services import projects
from app.sqlite_policy import copy_database
from app.vault import create_vault, decrypt_secret, encrypt_secret, unlock_vault
from scripts.benchmark_r03 import queries, seed


def v2_database(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        baseline_schema(connection)
        migration_history(connection)
        connection.execute("INSERT INTO schema_migrations(version,name) VALUES(2,'migration_history')")
        connection.execute("PRAGMA user_version=2")
        connection.execute("INSERT INTO projects(id,name) VALUES(1,'Index fixture')")
    return path


def dump(path):
    with closing(sqlite3.connect(path)) as connection:
        return tuple(connection.iterdump())


@pytest.fixture(scope="module")
def measured_databases(tmp_path_factory):
    directory = tmp_path_factory.mktemp("index-query-comparison")
    before = directory / "v2.db"
    with closing(sqlite3.connect(before)) as connection:
        baseline_schema(connection)
        migration_history(connection)
        connection.execute("INSERT INTO schema_migrations(version,name) VALUES(2,'migration_history')")
        connection.execute("PRAGMA user_version=2")
        seed(connection, projects=500, rows=5, target=250)
    after = directory / "v3.db"
    copy_database(before, after)
    db.init_db(after)
    return before, after


def vm_steps(connection, statement, parameters):
    ticks = [0]
    def tick():
        ticks[0] += 1
        return 0
    connection.set_progress_handler(tick, 1)
    try:
        rows = connection.execute(statement, parameters).fetchall()
    finally:
        connection.set_progress_handler(None, 0)
    return rows, ticks[0]


@pytest.mark.parametrize("case", ["urls", "notes", "checklist", "environment", "accounts", "home", "home_status", "notes_page_prototype"])
def test_measured_paths_preserve_full_results_and_reduce_vm_work(measured_databases, case):
    before, after = measured_databases
    with closing(sqlite3.connect(before)) as old, closing(sqlite3.connect(after)) as new:
        old.row_factory = sqlite3.Row
        cases = queries(old, 250)
        statement, parameters = cases[case]
        old.row_factory = None
        old_rows, old_steps = vm_steps(old, statement, parameters)
        new_rows, new_steps = vm_steps(new, statement, parameters)
        assert new_rows == old_rows
        assert new_steps < old_steps / 2  # Work, not machine-dependent timing.
        plan = " ".join(row[3] for row in new.execute("EXPLAIN QUERY PLAN " + statement, parameters))
        assert "INDEX idx_" in plan
        assert "TEMP B-TREE" not in plan


def test_complete_projection_unchanged_after_indexes(measured_databases):
    before, after = measured_databases
    with closing(db.connect(before)) as old, closing(db.connect(after)) as new:
        old_data, new_data = projects.project_detail(old, 250), projects.project_detail(new, 250)
        assert len(new_data.notes) == 250
        assert [tuple(row) for row in old_data.notes] == [tuple(row) for row in new_data.notes]
        assert old_data.access_accounts == new_data.access_accounts


def test_v2_upgrade_keeps_ciphertext_and_restart_does_not_repeat(tmp_path):
    path = v2_database(tmp_path / "encrypted-v2.db")
    with closing(db.connect(path)) as connection, connection:
        key = create_vault(connection, "test-only-index-master-password")
        ciphertext, nonce = encrypt_secret(key, 1, 9, "test-only-index-secret")
        connection.execute("INSERT INTO access_accounts(id,project_id,label,secret_ciphertext,secret_nonce) VALUES(9,1,'DB',?,?)", (ciphertext, nonce))
    original = dump(path)
    validate_backup(path)
    db.init_db(path)
    snapshot, = (tmp_path / "backups/migrations").glob("*.sqlite3")
    assert dump(snapshot) == original
    with closing(db.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert connection.execute("SELECT version,name FROM schema_migrations ORDER BY version").fetchall()[1][1] == "query_indexes"
        row = connection.execute("SELECT * FROM access_accounts").fetchone()
        assert (row["secret_ciphertext"], row["secret_nonce"]) == (ciphertext, nonce)
        key = unlock_vault(connection, "test-only-index-master-password")
        assert decrypt_secret(key, 1, 9, ciphertext, nonce) == "test-only-index-secret"
    before_restart = path.read_bytes()
    db.init_db(path)
    assert path.read_bytes() == before_restart
    assert len(list((tmp_path / "backups/migrations").glob("*.sqlite3"))) == 1


def test_partial_index_creation_failure_recovers_original_v2(tmp_path, monkeypatch):
    path = v2_database(tmp_path / "failed-index.db")
    original = dump(path)
    def fail(connection):
        for statement in QUERY_INDEXES[:3]:
            connection.execute(statement)
        connection.execute("UPDATE projects SET name='must roll back'")
        raise sqlite3.OperationalError("test-only index failure")
    monkeypatch.setattr(db, "MIGRATIONS", tuple(replace(step, apply=fail) if step.version == 3 else step for step in db.MIGRATIONS))
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert dump(path) == dump(result.value.snapshot_path) == original
    validate_backup(path)


@pytest.mark.parametrize("statement", QUERY_INDEXES, ids=[sql.split()[2] for sql in QUERY_INDEXES])
def test_v3_missing_index_is_rejected_before_startup_and_restore(tmp_path, statement):
    path = tmp_path / "missing-index.db"
    db.init_db(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"DROP INDEX {statement.split()[2]}")
    original = path.read_bytes()
    with pytest.raises(BackupValidationError):
        validate_backup(path)
    with pytest.raises(db.MigrationError):
        db.init_db(path)
    assert path.read_bytes() == original
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("wrong_definition", [
    "CREATE INDEX idx_notes_project_order ON notes(project_id,id ASC)",
    "CREATE INDEX idx_notes_project_order ON notes(id DESC,project_id)",
    "CREATE INDEX idx_notes_project_order ON notes(project_id,id DESC) WHERE priority='normal'",
])
def test_v3_same_name_wrong_definition_is_not_accepted(tmp_path, wrong_definition):
    path = tmp_path / "wrong-index.db"
    db.init_db(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP INDEX idx_notes_project_order")
        connection.execute(wrong_definition)
    with pytest.raises(BackupValidationError):
        validate_backup(path)


def test_index_validation_ignores_formatting_but_not_case_literal_changes(tmp_path):
    path = tmp_path / "format.db"
    db.init_db(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP INDEX idx_projects_updated")
        connection.execute("create index idx_projects_updated ON projects ( updated_at desc , id DESC )")
    validate_backup(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP INDEX idx_environment_project_order")
        connection.execute(QUERY_INDEXES[5].replace("'local'", "'lo cal'"))
    with pytest.raises(BackupValidationError):
        validate_backup(path)


def test_v2_index_name_collision_fails_safely_without_overwriting_user_index(tmp_path):
    path = v2_database(tmp_path / "collision.db")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE INDEX idx_notes_project_order ON notes(title)")
    original = dump(path)
    with pytest.raises(db.MigrationError) as result:
        db.init_db(path)
    assert result.value.recovered
    assert dump(path) == original


def test_v2_restore_upgrades_to_v3_and_keeps_pre_restore_snapshot(tmp_path):
    old = v2_database(tmp_path / "v2-upload.db")
    current = tmp_path / "current.db"
    db.init_db(current)
    original = dump(current)
    snapshot = restore_database(old, current)
    assert dump(snapshot) == original
    validate_backup(current)
    with closing(sqlite3.connect(current)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert connection.execute("SELECT name FROM projects").fetchone()[0] == "Index fixture"


@pytest.mark.parametrize("language,message", [
    ("zh-Hant", "資料庫的查詢索引不完整或不相容。"),
    ("en", "The database query indexes are incomplete or incompatible."),
])
def test_invalid_v3_index_upload_has_localized_error_without_replacing_current_data(tmp_path, monkeypatch, language, message):
    from app.main import create_app
    from tests.client import TestClient
    upload = tmp_path / "bad-upload.db"
    db.init_db(upload)
    with closing(sqlite3.connect(upload)) as connection:
        connection.execute("DROP INDEX idx_notes_project_order")
    current = tmp_path / "current.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    with TestClient(create_app()) as client:
        client.cookies.set("projmemo_language", language)
        original = current.read_bytes()
        response = client.post("/settings/backup/restore", files={"backup_file": ("invalid.sqlite3", upload.read_bytes())})
        assert response.status_code == 400
        assert message in response.text
        assert current.read_bytes() == original
