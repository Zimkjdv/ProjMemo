"""R09 lifecycle safety. All projects, secrets and backups are disposable fixtures."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import sqlite3

import pytest

from app import backup, db
from app.backup import BackupValidationError, restore_database, validate_backup
from app.errors import ApplicationError
from app.form_errors import FormDocument
from app.main import create_app
from app.migrations import baseline_schema, migration_history, query_indexes
from app.runtime import AppRuntime, VAULT_COOKIE_NAME
from app.services import accounts, content, lifecycle, projects, vault
from app.services.backups import backup_page_data, recovery_backup_path
from tests.client import TestClient
from tests.test_architecture import MUTATIONS, dump


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    path = tmp_path / "lifecycle.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    runtime = AppRuntime()
    key = vault.setup(runtime, "test-only-lifecycle-master", "test-only-lifecycle-master")
    token = vault.issue_session(runtime, key, None)
    projects.create_project(name="生命週期 / Lifecycle", status="handover", owner="Fixture team")
    projects.create_project(name="Unrelated project")
    content.add_url(project_id=1, title="Fixture URL", url="https://example.invalid/lifecycle")
    content.add_note(project_id=1, title="Fixture note", content_markdown="**Retained content**")
    content.add_checklist_item(project_id=1, title="Fixture checklist")
    content.add_environment_variable(project_id=1, key="FIXTURE_KEY")
    accounts.add_access_account(runtime=runtime, token=token, project_id=1, label="Fixture account",
                               secret_value="test-only-lifecycle-secret")
    accounts.add_access_account(runtime=runtime, token=token, project_id=2, label="Unrelated account",
                               secret_value="test-only-other-secret")
    return path, runtime, key, token


def transition(fixture, action, **overrides):
    _, runtime, _, _ = fixture
    row = lifecycle.management_data(1)["project"]
    values = dict(project_id=1, action=action, revision=row["revision"],
                  confirmation_name=row["name"], confirmed=True, runtime=runtime)
    return lifecycle.transition(**(values | overrides))


def children(path):
    with closing(sqlite3.connect(path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in (*lifecycle.CHILD_TABLES, "vault_config", "app_settings")}


@pytest.mark.parametrize("archived", [False, True])
def test_trash_restore_retains_ids_all_children_ciphertext_status_and_original_collection(fixture, archived):
    path, runtime, key, token = fixture
    before = children(path)
    if archived:
        transition(fixture, "archive")
        assert projects.list_projects(collection="archived")["total_count"] == 1
        assert projects.load_project(1)["status"] == "handover"
        assert projects.load_project_data(1).notes[0]["content_markdown"] == "**Retained content**"
    transition(fixture, "trash")
    assert vault.current_vault_key(runtime, token) is None
    assert projects.list_projects(collection="trash")["total_count"] == 1
    with pytest.raises(ApplicationError) as error:
        projects.load_project(1)
    assert error.value.status_code == 404
    transition(fixture, "restore")
    row = projects.load_project(1)
    assert row["status"] == "handover" and bool(row["archived_at"]) == archived
    assert children(path) == before
    token = vault.issue_session(runtime, key, None)
    assert accounts.reveal_secret(runtime, token, 1) == "test-only-lifecycle-secret"
    if archived:
        transition(fixture, "unarchive")
        assert projects.list_projects()["total_count"] == 2


def test_archive_remains_editable_and_updates_revision(fixture):
    transition(fixture, "archive")
    before = projects.load_project(1)["revision"]
    content.add_note(project_id=1, title="Archived edit", content_markdown="Allowed")
    assert projects.load_project(1)["revision"] == before + 1
    assert projects.load_project(1)["archived_at"]


@pytest.mark.parametrize("operation,values", MUTATIONS, ids=[op.__name__ for op, _ in MUTATIONS])
def test_all_child_mutations_on_trash_roll_back_completely(fixture, operation, values):
    path, _, _, _ = fixture
    transition(fixture, "trash")
    before = dump(path)
    with pytest.raises(ApplicationError) as error:
        operation(**values)
    assert error.value.status_code == 404
    assert dump(path) == before


@pytest.mark.parametrize("action", ["archive", "unarchive", "trash", "restore", "purge"])
def test_all_actions_require_exact_name_and_explicit_confirmation(fixture, action):
    if action in {"restore", "purge"}:
        transition(fixture, "trash")
    elif action == "unarchive":
        transition(fixture, "archive")
    before = dump(fixture[0])
    for overrides in ({"confirmed": False}, {"confirmation_name": "wrong"},
                      {"confirmation_name": "生命週期 / Lifecycle "}):
        with pytest.raises(ApplicationError) as error:
            transition(fixture, action, **overrides)
        assert error.value.status_code == 400
        assert dump(fixture[0]) == before
    assert not list(fixture[0].parent.glob("backups/projmemo-pre-delete-*"))


@pytest.mark.parametrize("operation,values", MUTATIONS, ids=[op.__name__ for op, _ in MUTATIONS])
def test_every_content_write_invalidates_old_lifecycle_confirmation(fixture, operation, values):
    old_revision = projects.load_project(1)["revision"]
    operation(**values)
    with pytest.raises(ApplicationError) as error:
        transition(fixture, "trash", revision=old_revision)
    assert error.value.status_code == 409
    assert not projects.load_project(1)["deleted_at"]


def test_project_edit_and_archive_roundtrip_invalidate_stale_confirmation(fixture):
    before = projects.load_project(1)["revision"]
    projects.update_project(project_id=1, name="生命週期 / Lifecycle")
    transition(fixture, "archive")
    transition(fixture, "unarchive")
    with pytest.raises(ApplicationError) as error:
        transition(fixture, "trash", revision=before)
    assert error.value.status_code == 409


@pytest.mark.parametrize("action", ["unarchive", "restore", "purge", "unknown"])
def test_invalid_state_or_action_does_not_change_data_or_create_backup(fixture, action):
    before = dump(fixture[0])
    with pytest.raises(ApplicationError) as error:
        transition(fixture, action)
    assert error.value.status_code == (404 if action == "unknown" else 409)
    assert dump(fixture[0]) == before
    assert not list(fixture[0].parent.glob("backups/projmemo-pre-delete-*"))


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_purge_snapshots_full_db_before_cascade_and_restore_recovers_encrypted_accounts(fixture, journal):
    path, runtime, key, _ = fixture
    with closing(sqlite3.connect(path)) as writer:
        writer.execute(f"PRAGMA journal_mode={journal}")
        transition(fixture, "trash")
        before = dump(path)
        rows = children(path)
        assert transition(fixture, "purge") == "/?collection=trash"
        saved, = path.parent.glob("backups/projmemo-pre-delete-*.sqlite3")
        validate_backup(saved)
        assert dump(saved) == before
        assert saved == recovery_backup_path(saved.name)
        assert backup_page_data()["recovery_backups"][0]["before_delete"]
        with closing(db.connect(path)) as connection:
            assert connection.execute("SELECT id FROM projects").fetchall()[0][0] == 2
            for table in lifecycle.CHILD_TABLES:
                assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=1").fetchone()[0] == 0
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        after = children(path)
        for table in ("vault_config", "app_settings"):
            assert after[table] == rows[table]
        assert after["access_accounts"] == [row for row in rows["access_accounts"] if row[1] == 2]
    restore_database(saved, path, on_replace=runtime.vault_sessions.clear)
    assert dump(path) == before
    transition(fixture, "restore")
    token = vault.issue_session(runtime, key, None)
    assert accounts.reveal_secret(runtime, token, 1) == "test-only-lifecycle-secret"


@pytest.mark.parametrize("failure", ["copy", "validate"])
def test_snapshot_failure_never_deletes_and_cleans_only_partial_snapshot(fixture, monkeypatch, failure):
    path = fixture[0]
    transition(fixture, "trash")
    before = dump(path)
    def fail(*args):
        raise OSError("test-only full disk") if failure == "copy" else BackupValidationError("test-only invalid snapshot")
    monkeypatch.setattr(backup, "create_database_backup" if failure == "copy" else "validate_backup", fail)
    with pytest.raises(ApplicationError) as error:
        transition(fixture, "purge")
    assert error.value.status_code == 503
    assert dump(path) == before
    assert not list(path.parent.glob("backups/projmemo-pre-delete-*"))


def test_delete_failure_rolls_back_and_keeps_valid_recovery_point(fixture, monkeypatch):
    path = fixture[0]
    transition(fixture, "trash")
    before = dump(path)
    original = db.connect
    row = lifecycle.management_data(1)["project"]
    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("test-only commit failure")
    def fail_commit(path):
        connection = sqlite3.connect(path, factory=FailedCommit)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    monkeypatch.setattr(db, "connect", fail_commit)
    with pytest.raises(sqlite3.OperationalError):
        lifecycle.transition(project_id=1, action="purge", revision=row["revision"],
            confirmation_name=row["name"], confirmed=True, runtime=fixture[1])
    monkeypatch.setattr(db, "connect", original)
    assert dump(path) == before
    saved, = path.parent.glob("backups/projmemo-pre-delete-*.sqlite3")
    validate_backup(saved)
    assert dump(saved) == before


def test_two_concurrent_confirmations_only_apply_once(fixture):
    revision = projects.load_project(1)["revision"]
    def attempt():
        try:
            transition(fixture, "trash", revision=revision)
            return 303
        except ApplicationError as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [303, 409]


def test_reveal_rechecks_project_after_slow_decryption(fixture, monkeypatch):
    _, runtime, _, token = fixture
    decrypt = accounts.decrypt_secret
    def trash_while_decrypting(*args):
        plaintext = decrypt(*args)
        transition(fixture, "trash")
        return plaintext
    monkeypatch.setattr(accounts, "decrypt_secret", trash_while_decrypting)
    with pytest.raises(ApplicationError) as error:
        accounts.reveal_secret(runtime, token, 1)
    assert error.value.status_code in {404, 423}


def native_form(markup, project_id, action):
    form = next(node for node in FormDocument(markup).root.walk()
                if node.tag == "form" and node.attrs.get("action") == f"/projects/{project_id}/lifecycle/{action}")
    return {node.attrs["name"]: node.attrs.get("value", "") for node in form.walk()
            if node.tag == "input" and node.attrs.get("type") == "hidden"}


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_native_forms_error_recovery_replay_trash_guards_restore_and_purge(fixture, language):
    path, runtime, key, _ = fixture
    vault.update_export_policy(runtime, fixture[3], True)
    with TestClient(create_app(runtime), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        url = "/projects/1/manage"
        page = client.get(url)
        assert page.status_code == 200 and "no-store" in page.headers["cache-control"]
        assert "test-only-lifecycle-secret" not in page.text and "secret_ciphertext" not in page.text
        data = native_form(page.text, 1, "archive") | {"confirmation_name": "wrong", "confirmed": "true"}
        failed = client.post("/projects/1/lifecycle/archive", data=data, headers={"Accept": "text/html"})
        assert failed.status_code == 400 and 'data-recovery-url="/projects/1/manage"' in failed.text
        assert "Enter the exact project name" in failed.text if language == "en" else "請輸入完整專案名稱" in failed.text
        data["confirmation_name"] = "生命週期 / Lifecycle"
        saved = client.post("/projects/1/lifecycle/archive", data=data, headers={"Accept": "text/html"})
        replay = client.post("/projects/1/lifecycle/archive", data=data, headers={"Accept": "text/html"})
        assert saved.status_code == replay.status_code == 303
        assert saved.headers["location"] == replay.headers["location"]
        assert client.get("/projects/1").status_code == 200
        for action in ("trash", "restore", "trash", "purge"):
            data = native_form(client.get(url).text, 1, action) | {"confirmation_name": "生命週期 / Lifecycle", "confirmed": "true"}
            response = client.post(f"/projects/1/lifecycle/{action}", data=data, headers={"Accept": "text/html"})
            assert response.status_code == 303
            if action == "trash":
                token = vault.issue_session(runtime, key, None)
                client.cookies.set(VAULT_COOKIE_NAME, token)
                for suffix in ("", "/edit", "/export.md", "/export.pdf"):
                    assert client.get("/projects/1" + suffix).status_code == 404
                assert client.get("/projects/1", headers={"X-ProjMemo-Fragment": "notes"}).status_code == 404
                assert client.post("/accounts/1/reveal").status_code == 404
                assert client.post("/projects/1/edit", data={"name": "Denied"}).status_code == 404
                for export_format in ("markdown", "pdf"):
                    export = client.post("/projects/1/export-with-secrets", data={"export_format": export_format, "confirm_sensitive_export": "true"})
                    assert export.status_code == 404  # Enabled policy and a fresh unlock cannot bypass Trash.
            elif action == "restore":
                assert client.get("/projects/1").status_code == 200
        assert client.get(url).status_code == 404
        assert response.headers["location"].count("?") == 1
        assert "collection=trash" in response.headers["location"]
        replay = client.post("/projects/1/lifecycle/purge", data=data, headers={"Accept": "text/html"})
        assert replay.status_code == 303 and replay.headers["location"] == response.headers["location"]
        assert len(list(path.parent.glob("backups/projmemo-pre-delete-*"))) == 1
        history = client.get("/settings/backup")
        assert "projmemo-pre-delete-" in history.text
        saved = backup_page_data()["recovery_backups"][0]["filename"]
        assert client.get("/settings/backup/files/" + saved).content.startswith(b"SQLite format 3")


def test_native_stale_confirmation_is_cleared_and_cross_origin_is_rejected(fixture):
    with TestClient(create_app(fixture[1]), follow_redirects=False) as client:
        data = native_form(client.get("/projects/1/manage").text, 1, "trash")
        data |= {"confirmation_name": "生命週期 / Lifecycle", "confirmed": "true"}
        content.add_note(project_id=1, title="New content", content_markdown="Review again")
        before = dump(fixture[0])
        response = client.post("/projects/1/lifecycle/trash", data=data, headers={"Accept": "text/html"})
        assert response.status_code == 409
        form = next(node for node in FormDocument(response.text).root.walk() if node.attrs.get("data-recovered-form"))
        controls = {node.attrs.get("name"): node for node in form.walk() if node.tag == "input"}
        assert controls["confirmation_name"].attrs.get("value") == ""
        assert "checked" not in controls["confirmed"].attrs
        rejected = client.post("/projects/1/lifecycle/trash", data=data, headers={"Origin": "https://example.invalid"})
        assert rejected.status_code == 403 and dump(fixture[0]) == before


@pytest.mark.parametrize("collection", ["active", "archived", "trash"])
def test_scoped_search_paging_and_view_urls_never_leak_other_collections(fixture, collection):
    with db.db_session(write=True) as connection:
        for scope in ("active", "archived", "trash"):
            for number in range(23):
                connection.execute("INSERT INTO projects(name,status,archived_at,deleted_at) VALUES(?, 'completed', ?, ?)",
                    (f"Scope {scope} {number:02}", "2026-10-16 00:00:00" if scope == "archived" else "",
                     "2026-10-16 00:00:00" if scope == "trash" else ""))
    for size in (10, 20, 50):
        values = projects.list_projects(collection=collection, q="Scope", status="completed", view="list", page_size=size, page=999)
        assert values["total_count"] == 23 and values["page"] == (23 + size - 1) // size
        assert all(f"Scope {collection} " in row["name"] for row in values["projects"])
        for field in ("card_view_url", "list_view_url", "clear_filter_url", "reset_list_url"):
            assert ("collection=" + collection in values[field]) == (collection != "active")
    with TestClient(create_app(fixture[1])) as client:
        response = client.get(f"/?collection={collection}&q=Scope&status=completed&view=list&page_size=20&page=2")
        assert response.status_code == 200
        assert response.text.count('class="project-list-row"') == 3
        assert ('name="collection"' in response.text) == (collection != "active")
    assert projects.list_projects(collection="invalid")["collection"] == "active"


def test_v3_to_v4_preserves_all_values_snapshots_once_and_supports_old_restore(tmp_path, monkeypatch):
    path = tmp_path / "v3.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        baseline_schema(connection)
        migration_history(connection)
        query_indexes(connection)
        connection.executemany("INSERT INTO schema_migrations(version,name) VALUES(?,?)", [(2, "migration_history"), (3, "query_indexes")])
        connection.execute("PRAGMA user_version=3")
        connection.execute("INSERT INTO projects(id,name,status,updated_at) VALUES(7,'Old v3','completed','2000-01-01 00:00:00')")
    original = dump(path)
    db.init_db(path)
    saved, = path.parent.glob("backups/migrations/*.sqlite3")
    assert dump(saved) == original
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT archived_at,deleted_at,revision FROM projects").fetchone() == ("", "", 0)
        assert connection.execute("SELECT name,status,updated_at FROM projects").fetchone() == ("Old v3", "completed", "2000-01-01 00:00:00")
    current = path.read_bytes()
    db.init_db(path)
    assert path.read_bytes() == current
    assert len(list(path.parent.glob("backups/migrations/*.sqlite3"))) == 1
    restore_database(saved, path)
    validate_backup(path)
    # Corrupt or downgraded v4 is rejected, not adopted as a legacy backup.
    for mutation in ("UPDATE projects SET revision=-1", "UPDATE projects SET deleted_at='bad'",
                     "DROP INDEX idx_projects_lifecycle", "ALTER TABLE projects DROP COLUMN revision"):
        candidate = tmp_path / "invalid.db"
        backup.create_database_backup(path, candidate)
        with closing(sqlite3.connect(candidate)) as connection, connection:
            connection.execute(mutation)
        with pytest.raises(BackupValidationError):
            validate_backup(candidate)


def test_partial_v4_failure_restores_v3_schema_and_data(tmp_path, monkeypatch):
    path = tmp_path / "v3-fail.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        baseline_schema(connection)
        migration_history(connection)
        query_indexes(connection)
        connection.executemany("INSERT INTO schema_migrations(version,name) VALUES(?,?)", [(2, "migration_history"), (3, "query_indexes")])
        connection.execute("PRAGMA user_version=3")
    before = dump(path)
    def fail(connection):
        connection.execute("ALTER TABLE projects ADD COLUMN archived_at TEXT NOT NULL DEFAULT ''")
        raise sqlite3.OperationalError("test-only interrupted v4")
    monkeypatch.setattr(db, "MIGRATIONS", tuple(replace(step, apply=fail) if step.version == 4 else step for step in db.MIGRATIONS))
    with pytest.raises(db.MigrationError) as error:
        db.init_db(path)
    assert error.value.recovered and dump(path) == before
