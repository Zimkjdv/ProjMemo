from pathlib import Path
import sqlite3

from tests.client import TestClient
import pytest

from app.backup import BackupValidationError, validate_backup
from app.db import SCHEMA_VERSION, init_db
from app.migrations import LIFECYCLE_INDEXES, QUERY_INDEXES
from app.vault import create_vault, decrypt_secret, encrypt_secret, unlock_vault, VaultError


@pytest.fixture
def backup(tmp_path, monkeypatch):
    path = tmp_path / "upload.sqlite3"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    init_db()
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO projects (name) VALUES ('backup project')")
        connection.row_factory = sqlite3.Row
        key = create_vault(connection, "test-only-master-password")
        connection.execute("INSERT INTO access_accounts (project_id, label) VALUES (1, 'test account')")
        ciphertext, nonce = encrypt_secret(key, 1, 1, "test-only-account-secret")
        connection.execute("UPDATE access_accounts SET secret_ciphertext=?, secret_nonce=?", (ciphertext, nonce))
    return path


def test_supported_backup_preserves_decryption_and_legacy_schema(backup):
    validate_backup(backup)
    with sqlite3.connect(backup) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        key = unlock_vault(connection, "test-only-master-password")
        row = connection.execute("SELECT * FROM access_accounts").fetchone()
        assert decrypt_secret(key, 1, 1, row["secret_ciphertext"], row["secret_nonce"]) == "test-only-account-secret"
        connection.execute("PRAGMA user_version = 0")
        connection.execute("DROP TABLE schema_migrations")
        for statement in QUERY_INDEXES + LIFECYCLE_INDEXES:
            connection.execute(f"DROP INDEX {statement.split()[2]}")
        for column in ("archived_at", "deleted_at", "revision"):
            connection.execute(f"ALTER TABLE projects DROP COLUMN {column}")
    validate_backup(backup)  # Existing pre-versioned vault backup.
    with sqlite3.connect(backup) as connection:
        for table in ("access_accounts", "vault_config", "app_settings"):
            connection.execute(f"DROP TABLE {table}")
    validate_backup(backup)  # Original pre-vault backup.


@pytest.mark.parametrize("mutation", [
    "PRAGMA user_version = 99",
    "DROP TABLE vault_config",
    "ALTER TABLE access_accounts DROP COLUMN purpose",
    "UPDATE vault_config SET kdf_memory_cost = 2147483647",
    "UPDATE vault_config SET kdf_iterations = 0",
    "UPDATE vault_config SET kdf_lanes = 99",
    "UPDATE vault_config SET salt = x'00'",
    "UPDATE vault_config SET verifier_nonce = x'00'",
    "UPDATE vault_config SET verifier_ciphertext = x'00'",
    "UPDATE access_accounts SET secret_nonce = NULL",
    "UPDATE access_accounts SET secret_ciphertext = x'00'",
    "UPDATE access_accounts SET project_id = 999",
    "UPDATE app_settings SET allow_secret_export = 2",
    "DELETE FROM app_settings",
    "DELETE FROM vault_config",
    "UPDATE projects SET description = x'00'",
    "CREATE TRIGGER unwanted AFTER INSERT ON projects BEGIN DELETE FROM notes; END",
    "CREATE VIEW unwanted AS SELECT * FROM projects",
])
def test_invalid_backup_is_rejected_before_replacing_current_data(backup, tmp_path, monkeypatch, mutation):
    with sqlite3.connect(backup) as connection:
        connection.execute(mutation)
    with pytest.raises(BackupValidationError):
        validate_backup(backup)

    current = tmp_path / "current.sqlite3"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    from app.main import app
    with TestClient(app, follow_redirects=False) as client:
        with sqlite3.connect(current) as connection:
            connection.execute("INSERT INTO projects (name) VALUES ('keep original')")
        before = current.read_bytes()
        response = client.post("/settings/backup/restore", files={"backup_file": ("upload.sqlite3", backup.read_bytes())})
        assert response.status_code == 400
        assert current.read_bytes() == before
        assert not (tmp_path / "backups").exists()


def test_unlock_rejects_invalid_metadata_without_deriving_key(backup, monkeypatch):
    with sqlite3.connect(backup) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("UPDATE vault_config SET kdf_memory_cost = 2147483647")
        def unexpected_derive(*args, **kwargs):
            pytest.fail("Invalid metadata must not reach the KDF")
        monkeypatch.setattr("app.vault._derive_key", unexpected_derive)
        with pytest.raises(VaultError):
            unlock_vault(connection, "test-only-master-password")


def test_legacy_restore_creates_missing_vault_tables(backup, tmp_path, monkeypatch):
    with sqlite3.connect(backup) as connection:
        connection.execute("DROP TABLE schema_migrations")
        for statement in QUERY_INDEXES + LIFECYCLE_INDEXES:
            connection.execute(f"DROP INDEX {statement.split()[2]}")
        for column in ("archived_at", "deleted_at", "revision"):
            connection.execute(f"ALTER TABLE projects DROP COLUMN {column}")
        for table in ("access_accounts", "vault_config", "app_settings"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version = 0")
    current = tmp_path / "legacy-current.sqlite3"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(current))
    from app.main import app
    with TestClient(app, follow_redirects=False) as client:
        response = client.post("/settings/backup/restore", files={"backup_file": ("legacy.sqlite3", backup.read_bytes())})
        assert response.status_code == 303
        assert "backup project" in client.get("/").text
    validate_backup(current)
    with sqlite3.connect(current) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
