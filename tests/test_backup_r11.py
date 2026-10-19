"""R11 uses disposable databases only, including every restore and cleanup."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
from io import BytesIO
from pathlib import Path
import sqlite3

import pytest

from app.backup import create_database_backup, recovery_directory
from app.backup_inspection import database_fingerprint, inspect_backup
from app.backup_plans import BackupPlans
from app.db import init_db
from app.errors import ApplicationError
from app.main import create_app
from app.migrations import MIGRATIONS
from app.runtime import AppRuntime
from app.services import backups
from app.vault import create_vault, decrypt_secret, encrypt_secret, unlock_vault
from tests.client import TestClient
from tests.test_backup_ui import BackupMarkup
from tests.test_migrations import legacy_database


@pytest.fixture
def sources(tmp_path, monkeypatch):
    current, incoming = tmp_path / "current.sqlite3", tmp_path / "incoming.sqlite3"
    for path, name in ((current, "Current-only fixture"), (incoming, "Incoming fixture")):
        init_db(path)
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO projects (id,name) VALUES (1,?)", (name,))
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    return current, incoming


def preview(client, incoming):
    return client.post("/settings/backup/preview", files={"backup_file": ("fixture.sqlite3", incoming.read_bytes())})


def token_from(response, action="/settings/backup/restore/confirm"):
    assert response.status_code == 200, response.text
    fields = BackupMarkup(response.text).forms[action]["inputs"]
    return next(item["value"] for item in fields if item.get("name") == "preview_token")


def restore(client, token, **overrides):
    return client.post("/settings/backup/restore/confirm", data={"preview_token": token,
                       "confirmation": "RESTORE", "acknowledged": "yes", **overrides})


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_preview_is_read_only_translated_and_does_not_render_project_contents(sources, language):
    current, incoming = sources
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        client.post("/settings/language", data={"language": language})
        before = current.read_bytes()
        key = application.state.runtime.vault_sessions.issue(b"x" * 32)
        response = preview(client, incoming)
        token_from(response)
        assert "no-store" in response.headers["cache-control"]
        assert current.read_bytes() == before
        assert not recovery_directory(current).exists()
        assert application.state.runtime.vault_sessions.get_key(key) == b"x" * 32
        assert "Current-only fixture" not in response.text and "Incoming fixture" not in response.text
        assert ("Compare before restoring" if language == "en" else "還原前內容比較") in response.text
        assert ("Keep all (default)" if language == "en" else "全部保留（預設）") in response.text
        assert len(list(current.parent.glob(".projmemo-upload-*"))) == 1
    assert not list(current.parent.glob(".projmemo-upload-*"))  # Graceful shutdown.


def test_cancel_removes_upload_without_snapshot_or_session_revocation(sources):
    current, incoming = sources
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        token = token_from(preview(client, incoming))
        assert client.post("/settings/backup/preview/cancel", data={"preview_token": token, "kind": "restore"}).status_code == 303
        assert not list(current.parent.glob(".projmemo-upload-*"))
        assert not recovery_directory(current).exists()
        assert restore(client, token).status_code == 409


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_language_switch_from_preview_targets_safe_get(sources, language):
    _, incoming = sources
    with TestClient(create_app(), follow_redirects=False) as client:
        response = preview(client, incoming)
        assert 'data-recovery-url="/settings/backup"' in response.text
        fields = BackupMarkup(response.text).forms["/settings/language"]["inputs"]
        return_to = next(field["value"] for field in fields if field.get("name") == "return_to")
        assert return_to == "/settings/backup"
        changed = client.post("/settings/language", data={"language": language, "return_to": return_to})
        assert changed.status_code == 303
        assert client.get(changed.headers["location"]).status_code == 200


@pytest.mark.parametrize("confirmation,acknowledged", [("", "yes"), ("restore", "yes"), ("RESTORE", ""), ("DELETE", "yes")])
def test_confirmation_is_enforced_by_server(sources, confirmation, acknowledged):
    current, incoming = sources
    with TestClient(create_app(), follow_redirects=False) as client:
        token = token_from(preview(client, incoming))
        marker = database_fingerprint(current)
        response = restore(client, token, confirmation=confirmation, acknowledged=acknowledged)
        assert response.status_code == 400
        assert 'id="restore-preview"' in response.text
        assert database_fingerprint(current) == marker
        assert not recovery_directory(current).exists()


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_confirmed_restore_preserves_recovery_and_revokes_sessions_once(sources, journal):
    current, incoming = sources
    with sqlite3.connect(current) as connection:
        connection.execute(f"PRAGMA journal_mode={journal}")
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        session = application.state.runtime.vault_sessions.issue(b"x" * 32)
        marker = database_fingerprint(current)
        token = token_from(preview(client, incoming))
        assert restore(client, token).status_code == 303
        assert application.state.runtime.vault_sessions.get_key(session) is None
        snapshots = list(recovery_directory(current).glob("projmemo-pre-restore-*.sqlite3"))
        assert len(snapshots) == 1 and database_fingerprint(snapshots[0]) == marker
        with sqlite3.connect(current) as connection:
            assert connection.execute("SELECT name FROM projects").fetchone()[0] == "Incoming fixture"
        assert restore(client, token).status_code == 409
        assert len(list(recovery_directory(current).glob("*.sqlite3"))) == 1
        assert not list(current.parent.glob(".projmemo-upload-*"))


@pytest.mark.parametrize("change", ["project", "settings"])
def test_database_changes_after_preview_abort_before_replacement(sources, change):
    current, incoming = sources
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        if change == "settings":
            with sqlite3.connect(current) as connection:
                create_vault(connection, "R11 current fixture master phrase")
        token = token_from(preview(client, incoming))
        with sqlite3.connect(current) as connection:
            connection.execute("UPDATE projects SET description='new work'" if change == "project"
                               else "UPDATE app_settings SET allow_secret_export=1")
        marker = database_fingerprint(current)
        session = application.state.runtime.vault_sessions.issue(b"x" * 32)
        assert restore(client, token).status_code == 409
        assert database_fingerprint(current) == marker
        assert application.state.runtime.vault_sessions.get_key(session) is not None
        assert restore(client, token).status_code == 409


def test_preview_identity_expiry_and_kind_binding(sources):
    current, incoming = sources
    now = [0]
    runtime = AppRuntime(backup_plans=BackupPlans(clock=lambda: now[0]))
    with TestClient(create_app(runtime), follow_redirects=False) as client:
        token = token_from(preview(client, incoming))
        browser = client.cookies.get("projmemo_csrf")
        with pytest.raises(ApplicationError):
            runtime.backup_plans.get(token, "other-browser", current, "restore")
        with pytest.raises(ApplicationError):
            runtime.backup_plans.get(token, browser, current, "cleanup")
        now[0] = 600
        runtime.backup_plans.purge_expired()
        assert not list(current.parent.glob(".projmemo-upload-*"))
        assert restore(client, token).status_code == 409


def test_modified_upload_is_rejected_without_touching_database(sources):
    current, incoming = sources
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        token = token_from(preview(client, incoming))
        staged = next(current.parent.glob(".projmemo-upload-*"))
        with sqlite3.connect(staged) as connection:
            connection.execute("UPDATE projects SET name='Changed staged fixture'")
        connection.close()
        marker = database_fingerprint(current)
        assert restore(client, token).status_code == 409
        assert database_fingerprint(current) == marker
        assert not list(current.parent.glob(".projmemo-upload-*"))


def test_state_marker_detects_changes_after_embedded_nul(sources):
    current, incoming = sources
    with sqlite3.connect(current) as connection:
        connection.execute("UPDATE projects SET description=?", ("fixture\x00before",))
    with TestClient(create_app(), follow_redirects=False) as client:
        token = token_from(preview(client, incoming))
        with sqlite3.connect(current) as connection:
            connection.execute("UPDATE projects SET description=?", ("fixture\x00after",))
        assert restore(client, token).status_code == 409


@pytest.mark.parametrize("version,vault", [(0, False), (0, True), (1, True), (2, True), (3, True)])
def test_old_backup_preview_does_not_migrate_but_confirmation_does(sources, tmp_path, version, vault):
    current, _ = sources
    old = legacy_database(tmp_path / "old.db", version=min(version, 1), vault=vault)
    if version >= 2:
        with sqlite3.connect(old) as connection:
            for step in MIGRATIONS:
                if 2 <= step.version <= version:
                    step.apply(connection)
                    connection.execute("INSERT INTO schema_migrations(version,name) VALUES (?,?)", (step.version, step.name))
            connection.execute(f"PRAGMA user_version={version}")
    before = old.read_bytes()
    with TestClient(create_app(), follow_redirects=False) as client:
        response = preview(client, old)
        token = token_from(response)
        assert f"v{version}" in response.text and "v4" in response.text
        assert old.read_bytes() == before
        assert restore(client, token).status_code == 303
        assert inspect_backup(current)["version"] == 4
        assert list((recovery_directory(current) / "migrations").glob("*.sqlite3"))


def test_vault_preview_shows_only_metadata_and_restore_preserves_original_password(sources):
    current, incoming = sources
    master, secret = "R11 test-only master phrase", "R11 test-only account secret"
    with sqlite3.connect(incoming) as connection:
        key = create_vault(connection, master)
        ciphertext, nonce = encrypt_secret(key, 1, 1, secret)
        connection.execute("INSERT INTO access_accounts(id,project_id,label,secret_ciphertext,secret_nonce) VALUES (1,1,'fixture',?,?)", (ciphertext, nonce))
        connection.execute("UPDATE app_settings SET allow_secret_export=1")
    with TestClient(create_app(), follow_redirects=False) as client:
        response = preview(client, incoming)
        assert master not in response.text and secret not in response.text and ciphertext.hex() not in response.text
        assert "備份允許含密碼匯出" in response.text
        assert restore(client, token_from(response)).status_code == 303
        with sqlite3.connect(current) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM access_accounts").fetchone()
            assert decrypt_secret(unlock_vault(connection, master), 1, 1, row["secret_ciphertext"], row["secret_nonce"]) == secret


def test_preview_counts_include_archived_trashed_and_all_five_content_types(sources):
    _, incoming = sources
    with sqlite3.connect(incoming) as connection:
        connection.execute("INSERT INTO projects(id,name,archived_at) VALUES (2,'Archived fixture','2026-10-19 01:00:00')")
        connection.execute("INSERT INTO projects(id,name,deleted_at) VALUES (3,'Trashed fixture','2026-10-19 01:00:00')")
        connection.execute("INSERT INTO project_urls(project_id,title,url) VALUES (3,'URL','https://example.invalid')")
        connection.execute("INSERT INTO notes(project_id,title,content_markdown) VALUES (2,'Note','fixture body')")
        connection.execute("INSERT INTO checklist_items(project_id,title) VALUES (3,'Checklist')")
        connection.execute("INSERT INTO environment_variables(project_id,key) VALUES (1,'FIXTURE_KEY')")
        connection.execute("INSERT INTO access_accounts(project_id,label) VALUES (2,'Account')")
    values = inspect_backup(incoming)
    assert (values["active"], values["archived"], values["trash"]) == (1, 1, 1)
    assert values["counts"] == {"projects": 3, "project_urls": 1, "notes": 1,
                                "checklist_items": 1, "environment_variables": 1, "access_accounts": 1}


def test_invalid_upload_and_capacity_failure_leave_no_extra_staging_files(sources):
    current, incoming = sources
    runtime = AppRuntime(backup_plans=BackupPlans(capacity=1))
    with TestClient(create_app(runtime), follow_redirects=False) as client:
        response = client.post("/settings/backup/preview", files={"backup_file": ("bad.db", b"not sqlite")})
        assert response.status_code == 400 and not list(current.parent.glob(".projmemo-upload-*"))
        token_from(preview(client, incoming))
        assert preview(client, incoming).status_code == 503
        assert len(list(current.parent.glob(".projmemo-upload-*"))) == 1


def test_plan_consumption_is_atomic_and_bound_to_database(tmp_path):
    plans = BackupPlans()
    database = tmp_path / "fixture.db"
    token = plans.issue("browser", database, "cleanup", {})
    with pytest.raises(ApplicationError):
        plans.get(token, "browser", tmp_path / "other.db", "cleanup")
    def consume(_):
        try:
            with plans.consume(token, "browser", database, "cleanup"):
                return True
        except ApplicationError:
            return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(consume, range(2))) == [False, True]


def test_locked_temporary_upload_is_retried_and_still_counts_toward_capacity(tmp_path, monkeypatch):
    plans = BackupPlans(capacity=1)
    upload = tmp_path / "private-preview.sqlite3"
    upload.write_bytes(b"R11 disposable upload")
    database = tmp_path / "fixture.db"
    token = plans.issue("browser", database, "restore", {}, upload=upload)
    unlink = Path.unlink
    def blocked(path, *args, **kwargs):
        if path == upload:
            raise PermissionError("R11 simulated external lock")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", blocked)
    with plans.consume(token, "browser", database, "restore"):
        pass
    assert upload.exists() and upload in plans.pending_removals
    with pytest.raises(ApplicationError):
        plans.issue("browser", database, "cleanup", {})
    monkeypatch.setattr(Path, "unlink", unlink)
    plans.purge_expired()
    assert not upload.exists() and not plans.pending_removals


def test_unrelated_browser_and_missing_csrf_cannot_confirm(sources):
    current, incoming = sources
    application = create_app()
    with TestClient(application, follow_redirects=False) as first:
        token = token_from(preview(first, incoming))
        from fastapi.testclient import TestClient as RawTestClient
        with RawTestClient(application, base_url="http://127.0.0.1", follow_redirects=False) as other:
            assert restore(other, token).status_code == 403
            response = other.get("/")
            csrf = other.cookies.get("projmemo_csrf")
            assert response.status_code == 200
            assert other.post("/settings/backup/restore/confirm", data={"preview_token": token, "confirmation": "RESTORE", "acknowledged": "yes"},
                              headers={"X-CSRF-Token": csrf}).status_code == 409


@pytest.mark.parametrize("path", ["/settings/backup/restore/confirm", "/settings/backup/cleanup/confirm", "/"])
def test_http_request_does_not_inherit_another_requests_database_context(sources, path):
    from app.database_access import DatabaseAccessMiddleware, _admitted, _maintenance, access_for
    current, _ = sources
    access = access_for(current)
    async def endpoint(scope, receive, send):
        assert _maintenance.get() is None
        assert (_admitted.get() is access) == (path == "/")
        assert access._active == (2 if path == "/" else 1)
    async def receive():
        return {"type": "http.request", "body": b""}
    async def send(message):
        pass
    with access.operation():
        asyncio.run(DatabaseAccessMiddleware(endpoint)({"type": "http", "path": path}, receive, send))
        assert _admitted.get() is access and access._active == 1
    assert access._active == 0


def test_inherited_maintenance_does_not_admit_a_new_http_request(sources):
    from app.database_access import DatabaseAccessMiddleware, access_for
    current, _ = sources
    messages = []
    async def endpoint(scope, receive, send):
        pytest.fail("A new HTTP request must not borrow the previous maintenance lease")
    async def receive():
        return {"type": "http.request", "body": b""}
    async def send(message):
        messages.append(message)
    with access_for(current).maintenance():
        asyncio.run(DatabaseAccessMiddleware(endpoint)({"type": "http", "path": "/", "headers": []}, receive, send))
    assert messages[0]["status"] == 503
