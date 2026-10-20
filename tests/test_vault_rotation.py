"""R13: synthetic old-key backups, atomic rekey, session/race and HTTP regressions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import threading

import pytest

from app import db, vault as crypto
from app.backup import is_recovery_backup_filename, restore_database, validate_backup
from app.backup_retention import recovery_files
from app.database_access import DatabaseBusyError, access_for
from app.errors import ApplicationError
from app.form_errors import FormDocument
from app.main import create_app
from app.runtime import AppRuntime
from app.services import accounts, projects, vault
from tests.client import TestClient

OLD = "  synthetic old master phrase  "
NEW = "  新的主密碼 synthetic passphrase  "
SECRETS = [" leading and trailing ", "tabs\tand\nnewlines<&>中文", "third synthetic secret"]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    path = tmp_path / "rotation.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    runtime = AppRuntime()
    old_key = vault.setup(runtime, OLD, OLD)
    tokens = [vault.issue_session(runtime, old_key, None) for _ in range(2)]
    for number, secret in enumerate(SECRETS):
        project = projects.create_project(name=f"R13 synthetic {number}", owner="Fixture owner", tags="fixture")
        accounts.add_access_account(runtime=runtime, token=tokens[0], project_id=project,
                                    label=f"Synthetic account {number}", secret_value=secret)
    accounts.add_access_account(runtime=runtime, token=tokens[0], project_id=1, label="Metadata only", secret_reference="External vault")
    with db.db_session(write=True) as connection:
        connection.execute("UPDATE projects SET archived_at = '2000-01-01' WHERE id = 2")
        connection.execute("UPDATE projects SET deleted_at = '2000-01-01' WHERE id = 3")
    vault.update_export_policy(runtime, tokens[0], True)
    return path, runtime, tokens


def rows(path, table):
    with closing(db.connect(path)) as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def rotate(runtime, **changes):
    values = dict(current_password=OLD, new_password=NEW, confirmation=NEW, confirmed=True)
    return vault.change_master_password(runtime, **(values | changes))


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_rotation_reencrypts_every_lifecycle_and_preserves_metadata_and_old_backup(fixture, journal):
    path, runtime, tokens = fixture
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA journal_mode = {journal}")
    before = rows(path, "access_accounts")
    projects_before = rows(path, "projects")
    config_before = rows(path, "vault_config")[0]
    saved = rotate(runtime)
    assert saved.is_file() and is_recovery_backup_filename(saved.name)
    assert saved.name.startswith("projmemo-pre-vault-change-")
    validate_backup(saved)
    assert any(item["filename"] == saved.name for item in recovery_files(path))
    with closing(db.connect(path)) as connection:
        with pytest.raises(crypto.InvalidMasterPassword):
            crypto.unlock_vault(connection, OLD)
        new_key = crypto.unlock_vault(connection, NEW)
    config = rows(path, "vault_config")[0]
    for field in ("salt", "verifier_nonce", "verifier_ciphertext"):
        assert config[field] != config_before[field]
    assert config["created_at"] == config_before["created_at"]
    for number, (previous, current) in enumerate(zip(before, rows(path, "access_accounts"))):
        assert {key: value for key, value in previous.items() if key not in {"secret_ciphertext", "secret_nonce"}} == {
            key: value for key, value in current.items() if key not in {"secret_ciphertext", "secret_nonce"}}
        if number < 3:
            assert current["secret_nonce"] != previous["secret_nonce"]
            assert current["secret_ciphertext"] != previous["secret_ciphertext"]
            assert crypto.decrypt_secret(new_key, current["project_id"], current["id"],
                current["secret_ciphertext"], current["secret_nonce"]) == SECRETS[number]
        else:
            assert current["secret_ciphertext"] is None and current["secret_nonce"] is None
    assert projects_before == rows(path, "projects")
    assert rows(path, "app_settings")[0]["allow_secret_export"] == 1
    assert all(runtime.vault_sessions.get_key(token) is None for token in tokens)
    assert vault.unlock(AppRuntime(), NEW) == new_key  # Restart needs no retained old key.
    with closing(db.connect(saved)) as connection:
        old_key = crypto.unlock_vault(connection, OLD)
        with pytest.raises(crypto.InvalidMasterPassword):
            crypto.unlock_vault(connection, NEW)
        assert rows(saved, "access_accounts") == before
        row = connection.execute("SELECT * FROM access_accounts WHERE id = 1").fetchone()
        assert crypto.decrypt_secret(old_key, row["project_id"], row["id"], row["secret_ciphertext"], row["secret_nonce"]) == SECRETS[0]
    for file in (path, saved):
        assert all(value.encode("utf-8") not in file.read_bytes() for value in [OLD, NEW, *SECRETS])
    restore_database(saved, path, on_replace=runtime.vault_sessions.clear)
    assert vault.unlock(runtime, OLD) == old_key
    with pytest.raises(ApplicationError):
        vault.unlock(runtime, NEW)


@pytest.mark.parametrize("changes,status", [
    ({"current_password": "wrong synthetic password"}, 401),
    ({"new_password": "short", "confirmation": "short"}, 400),
    ({"new_password": "x" * 1025, "confirmation": "x" * 1025}, 400),
    ({"confirmation": "mismatch"}, 400), ({"new_password": OLD, "confirmation": OLD}, 400),
    ({"confirmed": False}, 400), ({"current_password": "x" * 1025}, 400),
])
def test_validation_and_authentication_do_not_write_or_create_backups(fixture, changes, status):
    path, runtime, tokens = fixture
    before = path.read_bytes()
    with pytest.raises(ApplicationError) as error:
        rotate(runtime, **changes)
    assert error.value.status_code == status
    assert path.read_bytes() == before
    assert not list(path.parent.glob("backups/projmemo-pre-vault-change-*"))
    assert all(runtime.vault_sessions.get_key(token) for token in tokens)


def test_shared_rate_limit_cannot_be_bypassed_by_an_unlocked_cookie(fixture):
    _, runtime, _ = fixture
    runtime.unlock_attempt_limiter = crypto.UnlockAttemptLimiter(max_attempts=1)
    with pytest.raises(ApplicationError) as wrong:
        rotate(runtime, current_password="wrong synthetic password")
    assert wrong.value.status_code == 401
    with pytest.raises(ApplicationError) as limited:
        rotate(runtime)
    assert limited.value.status_code == 429


@pytest.mark.parametrize("configured", [False, True])
def test_empty_or_unconfigured_vault_does_not_require_dummy_accounts(tmp_path, monkeypatch, configured):
    path = tmp_path / "empty.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    runtime = AppRuntime()
    if configured:
        vault.setup(runtime, OLD, OLD)
        assert rotate(runtime).is_file()
        assert vault.unlock(runtime, NEW)
    else:
        with pytest.raises(ApplicationError) as error:
            rotate(runtime)
        assert error.value.status_code == 409
        assert rows(path, "vault_config") == []
        assert not list(path.parent.glob("backups/*"))


def test_validated_nondefault_kdf_parameters_are_preserved(tmp_path, monkeypatch):
    path = tmp_path / "custom-kdf.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    _, values = crypto._new_vault_material(OLD, memory_cost=32768, iterations=2, lanes=2)
    with db.db_session(write=True) as connection:
        connection.execute("INSERT INTO vault_config (id, salt, verifier_nonce, verifier_ciphertext, "
            "kdf_memory_cost, kdf_iterations, kdf_lanes) VALUES (1, ?, ?, ?, ?, ?, ?)", values)
    runtime = AppRuntime()
    rotate(runtime)
    assert vault.unlock(runtime, NEW)
    row = rows(path, "vault_config")[0]
    assert (row["kdf_memory_cost"], row["kdf_iterations"], row["kdf_lanes"]) == (32768, 2, 2)


@pytest.mark.parametrize("phase", ["backup", "second-secret", "after-metadata", "early-commit", "bad-roundtrip", "corrupt-secret"])
def test_failures_roll_back_all_encrypted_rows_and_keep_recovery_copy(fixture, monkeypatch, phase):
    path, runtime, _ = fixture
    if phase == "corrupt-secret":
        with db.db_session(write=True) as connection:
            connection.execute("UPDATE access_accounts SET secret_ciphertext = ? WHERE id = 2", (b"x" * 40,))
    before_accounts, before_config = rows(path, "access_accounts"), rows(path, "vault_config")
    original_encrypt, original_rekey = crypto.encrypt_secret, vault.reencrypt_vault
    calls = 0
    def encrypt(*args):
        nonlocal calls
        calls += 1
        if phase == "second-secret" and calls == 2:
            raise RuntimeError("synthetic exception containing passwords must not be returned")
        ciphertext, nonce = original_encrypt(*args)
        return (b"x" * len(ciphertext), nonce) if phase == "bad-roundtrip" else (ciphertext, nonce)
    def rekey(connection, *args):
        result = original_rekey(connection, *args)
        if phase == "after-metadata":
            raise RuntimeError("synthetic failure after all updates")
        if phase == "early-commit":
            connection.commit()
        return result
    monkeypatch.setattr(crypto, "encrypt_secret", encrypt)
    monkeypatch.setattr(vault, "reencrypt_vault", rekey)
    if phase == "backup":
        monkeypatch.setattr(vault, "create_vault_change_snapshot", lambda path: (_ for _ in ()).throw(OSError("synthetic disk full")))
    with pytest.raises(ApplicationError) as error:
        rotate(runtime)
    assert error.value.status_code == 503 and OLD not in error.value.detail and NEW not in error.value.detail
    assert rows(path, "access_accounts") == before_accounts and rows(path, "vault_config") == before_config
    assert bool(list(path.parent.glob("backups/projmemo-pre-vault-change-*"))) == (phase != "backup")
    assert access_for(path).accepting_requests()


@pytest.mark.parametrize("phase", ["commit", "post-commit", "rollback"])
def test_commit_and_rollback_failures_are_not_silently_reported_as_success(fixture, monkeypatch, phase):
    path, runtime, tokens = fixture
    original_connect, original_rekey = db.connect, vault.reencrypt_vault
    before = rows(path, "access_accounts")
    failed = False
    class Connection:
        def __init__(self, base): self.base = base
        def __getattr__(self, name): return getattr(self.base, name)
        def commit(self):
            nonlocal failed
            if phase in {"commit", "post-commit"} and not failed:
                failed = True
                if phase == "post-commit": self.base.commit()
                raise sqlite3.OperationalError("synthetic commit failure")
            self.base.commit()
        def rollback(self):
            if phase == "rollback": raise sqlite3.OperationalError("synthetic rollback failure")
            self.base.rollback()
    monkeypatch.setattr(db, "connect", lambda path=None: Connection(original_connect(path)))
    if phase == "rollback":
        def rekey(*args):
            original_rekey(*args)
            raise RuntimeError("synthetic write failure")
        monkeypatch.setattr(vault, "reencrypt_vault", rekey)
    with pytest.raises((ApplicationError, DatabaseBusyError)):
        rotate(runtime)
    assert all(runtime.vault_sessions.get_key(token) is None for token in tokens)
    assert access_for(path).accepting_requests() == (phase == "commit")
    if phase != "post-commit":
        assert rows(path, "access_accounts") == before
    saved, = path.parent.glob("backups/projmemo-pre-vault-change-*.sqlite3")
    validate_backup(saved)


def test_rotation_drains_old_key_requests_and_revokes_before_reopening(fixture, monkeypatch):
    path, runtime, tokens = fixture
    active, release, entered = threading.Event(), threading.Event(), threading.Event()
    access = access_for(path)
    original = vault.reencrypt_vault
    def old_request():
        with access.operation():
            key = vault.require_vault_key(runtime, tokens[0])
            active.set()
            assert release.wait(5)
            return vault.issue_session(runtime, key, None)
    def rekey(*args):
        entered.set()
        assert late.result(5)
        with pytest.raises(DatabaseBusyError):
            # A separate context/request must not borrow the rotation admission.
            with ThreadPoolExecutor(1) as pool:
                pool.submit(lambda: projects.load_project(1)).result(5)
        return original(*args)
    monkeypatch.setattr(vault, "reencrypt_vault", rekey)
    with ThreadPoolExecutor(2) as pool:
        late = pool.submit(old_request)
        assert active.wait(5)
        rotation = pool.submit(rotate, runtime)
        assert not entered.wait(.1)
        release.set()
        saved = rotation.result(10)
        late_token = late.result(5)
    assert saved.is_file() and runtime.vault_sessions.get_key(late_token) is None
    assert access.accepting_requests()


@pytest.mark.parametrize("update", [False, True])
def test_service_writers_cannot_capture_old_key_before_admission(fixture, monkeypatch, update):
    path, runtime, tokens = fixture
    captured, release, rekeying = threading.Event(), threading.Event(), threading.Event()
    original_key, original_rekey = accounts.current_vault_key, vault.reencrypt_vault
    def key(*args):
        result = original_key(*args)
        captured.set()
        assert release.wait(5)
        return result
    def rekey(*args):
        rekeying.set()
        return original_rekey(*args)
    monkeypatch.setattr(accounts, "current_vault_key", key)
    monkeypatch.setattr(vault, "reencrypt_vault", rekey)
    with ThreadPoolExecutor(2) as pool:
        writer = pool.submit(accounts.update_access_account if update else accounts.add_access_account,
            runtime=runtime, token=tokens[0], label="In-flight synthetic save", secret_value="late synthetic secret",
            **({"account_id": 1} if update else {"project_id": 1}))
        assert captured.wait(5)
        rotating = pool.submit(rotate, runtime)
        try:
            assert not rekeying.wait(.1)
        finally:
            release.set()
        writer.result(10)
        rotating.result(10)
    new_key = vault.unlock(runtime, NEW)
    row = next(row for row in rows(path, "access_accounts") if row["label"] == "In-flight synthetic save")
    assert crypto.decrypt_secret(new_key, row["project_id"], row["id"], row["secret_ciphertext"], row["secret_nonce"]) == "late synthetic secret"


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_native_password_change_retry_no_refill_replay_and_backup_download(fixture, language):
    path, runtime, tokens = fixture
    with TestClient(create_app(runtime), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        client.cookies.set("projmemo_vault", tokens[0], domain="127.0.0.1", path="/")
        page = client.get("/settings/vault")
        form = next(node for node in FormDocument(page.text).root.walk() if node.tag == "form"
                    and node.attrs.get("action") == "/settings/vault/change-password")
        token = next(node.attrs["value"] for node in form.walk() if node.attrs.get("name") == "_submission_token")
        base = dict(current_master_password=OLD, new_master_password=NEW, confirm_new_password=NEW,
                    confirm_password_change="true", _submission_token=token)
        failed = client.post("/settings/vault/change-password", data=base | {"current_master_password": "wrong synthetic phrase"}, headers={"Accept": "text/html"})
        assert failed.status_code == 401
        assert OLD not in failed.text and NEW not in failed.text and "wrong synthetic phrase" not in failed.text
        assert 'data-recovery-url="/settings/vault"' in failed.text
        recovered = FormDocument(failed.text)
        assert all(not node.attrs.get("value") for node in recovered.root.walk() if node.attrs.get("type") == "password")
        response = client.post("/settings/vault/change-password", data=base, headers={"Accept": "text/html"})
        assert response.status_code == 303 and "notice=password-changed" in response.headers["location"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert client.post("/settings/vault/change-password", data=base, headers={"Accept": "text/html"}).status_code == 303
        saved, = path.parent.glob("backups/projmemo-pre-vault-change-*.sqlite3")
        downloaded = client.get(f"/settings/backup/files/{saved.name}")
        assert downloaded.status_code == 200 and downloaded.content == saved.read_bytes()
        assert saved.name in client.get("/settings/backup").text
        assert client.get("/settings/vault/status").json()["unlocked"] is False
        assert client.post("/settings/vault/change-password", data=base, headers={"X-CSRF-Token": "bad"}).status_code == 403
        assert client.post("/settings/vault/unlock", data={"master_password": NEW}).status_code == 303
        assert client.post("/accounts/1/reveal").json()["secret"] == SECRETS[0]


def test_http_maintenance_blocks_parallel_unlock_and_write_but_keeps_recovery_downloads(fixture, monkeypatch):
    path, runtime, _ = fixture
    entered, release = threading.Event(), threading.Event()
    original = vault.reencrypt_vault
    def paused(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(vault, "reencrypt_vault", paused)
    with TestClient(create_app(runtime), follow_redirects=False) as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client.post, "/settings/vault/change-password", data=dict(
            current_master_password=OLD, new_master_password=NEW, confirm_new_password=NEW, confirm_password_change="true"))
        try:
            assert entered.wait(10)
            assert client.get("/settings/vault/status").status_code == 503
            assert client.post("/settings/vault/unlock", data={"master_password": OLD}).status_code == 503
            assert client.post("/projects/1/notes", data={"title": "Not written", "content_markdown": "blocked"}).status_code == 503
            saved, = path.parent.glob("backups/projmemo-pre-vault-change-*.sqlite3")
            assert client.get(f"/settings/backup/files/{saved.name}").status_code == 200
            assert client.get("/settings/backup").status_code == 200
        finally:
            release.set()
        assert pending.result(10).status_code == 303
    assert rows(path, "notes") == []
