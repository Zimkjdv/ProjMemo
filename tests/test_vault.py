from pathlib import Path
import sqlite3

from tests.client import TestClient


MASTER_PASSWORD = "correct horse battery staple"
SAVED_SECRET = "vault-secret-test-value-42"


def _create_project(client: TestClient) -> int:
    response = client.post(
        "/projects/new",
        data={
            "name": "Vault integration project",
            "description": "credential vault integration fixture",
            "status": "maintenance",
            "owner": "Test owner",
            "tags": "test",
        },
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_vault_encrypts_secrets_and_regular_exports_never_include_them(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "vault-test.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(database_path))

    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        setup_page = client.get("/settings/vault")
        assert setup_page.status_code == 200
        assert 'name="master_password"' in setup_page.text

        setup_response = client.post(
            "/settings/vault/setup",
            data={"master_password": MASTER_PASSWORD, "confirm_password": MASTER_PASSWORD},
        )
        assert setup_response.status_code == 303
        assert client.cookies.get("projmemo_vault")

        project_id = _create_project(client)
        account_response = client.post(
            f"/projects/{project_id}/accounts",
            data={
                "label": "Test website account",
                "category": "website",
                "environment": "test",
                "endpoint": "https://test.example.invalid/login",
                "username": "test-user",
                "secret_value": SAVED_SECRET,
            },
        )
        assert account_response.status_code == 303

        with sqlite3.connect(database_path) as connection:
            account_id, ciphertext, nonce = connection.execute(
                "SELECT id, secret_ciphertext, secret_nonce FROM access_accounts WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        assert ciphertext
        assert nonce
        assert SAVED_SECRET.encode("utf-8") not in ciphertext

        backup_response = client.get("/settings/backup/download")
        assert backup_response.status_code == 200
        backup_path = tmp_path / "vault-backup.sqlite3"
        backup_path.write_bytes(backup_response.content)
        with sqlite3.connect(backup_path) as backup_connection:
            backup_ciphertext = backup_connection.execute(
                "SELECT secret_ciphertext FROM access_accounts WHERE id = ?", (account_id,)
            ).fetchone()[0]
        assert backup_ciphertext == ciphertext
        assert SAVED_SECRET.encode("utf-8") not in backup_ciphertext

        detail_response = client.get(f"/projects/{project_id}")
        assert detail_response.status_code == 200
        assert SAVED_SECRET not in detail_response.text
        assert "••••••••••" in detail_response.text

        markdown_response = client.get(f"/projects/{project_id}/export.md")
        assert markdown_response.status_code == 200
        assert SAVED_SECRET not in markdown_response.text

        observed_pdf_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_pdf(*args, **kwargs):
            observed_pdf_calls.append((args, kwargs))
            return b"%PDF-1.4\nregular export fixture"

        monkeypatch.setattr("app.services.exports.generate_project_pdf", fake_pdf)
        pdf_response = client.get(f"/projects/{project_id}/export.pdf")
        assert pdf_response.status_code == 200
        safe_accounts = observed_pdf_calls[-1][0][5]
        assert safe_accounts[0]["has_secret"]
        assert "secret_value" not in safe_accounts[0]
        assert SAVED_SECRET.encode("utf-8") not in pdf_response.content

        reveal_response = client.post(f"/accounts/{account_id}/reveal")
        assert reveal_response.status_code == 200
        assert reveal_response.json() == {"secret": SAVED_SECRET}
        assert reveal_response.headers["cache-control"].startswith("no-store")

        client.post("/settings/vault/lock")
        locked_reveal = client.post(f"/accounts/{account_id}/reveal")
        assert locked_reveal.status_code == 423

        wrong_password = client.post(
            "/settings/vault/unlock", data={"master_password": "this is not the master password"}
        )
        assert wrong_password.status_code == 401
        correct_password = client.post(
            "/settings/vault/unlock", data={"master_password": MASTER_PASSWORD}
        )
        assert correct_password.status_code == 303


def test_sensitive_export_requires_policy_unlock_and_confirmation(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "sensitive-export-test.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(database_path))

    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project_id = _create_project(client)
        client.post(
            "/settings/vault/setup",
            data={"master_password": MASTER_PASSWORD, "confirm_password": MASTER_PASSWORD},
        )
        client.post(
            f"/projects/{project_id}/accounts",
            data={
                "label": "Database test account",
                "category": "database",
                "environment": "test",
                "username": "db-user",
                "secret_value": SAVED_SECRET,
            },
        )

        sensitive_payload = {
            "export_format": "markdown",
            "confirm_sensitive_export": "true",
        }
        blocked_by_default = client.post(
            f"/projects/{project_id}/export-with-secrets", data=sensitive_payload
        )
        assert blocked_by_default.status_code == 403

        enable_response = client.post(
            "/settings/vault/export-policy", data={"allow_secret_export": "true"}
        )
        assert enable_response.status_code == 303

        safe_markdown = client.get(f"/projects/{project_id}/export.md")
        assert safe_markdown.status_code == 200
        assert SAVED_SECRET not in safe_markdown.text

        observed_pdf_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_pdf(*args, **kwargs):
            observed_pdf_calls.append((args, kwargs))
            return b"%PDF-1.4\nexport fixture"

        monkeypatch.setattr("app.services.exports.generate_project_pdf", fake_pdf)
        safe_pdf = client.get(f"/projects/{project_id}/export.pdf")
        assert safe_pdf.status_code == 200
        safe_accounts = observed_pdf_calls[-1][0][5]
        assert "secret_value" not in safe_accounts[0]

        client.post("/settings/vault/lock")
        blocked_while_locked = client.post(
            f"/projects/{project_id}/export-with-secrets", data=sensitive_payload
        )
        assert blocked_while_locked.status_code == 423

        unlock_response = client.post(
            "/settings/vault/unlock", data={"master_password": MASTER_PASSWORD}
        )
        assert unlock_response.status_code == 303

        missing_confirmation = client.post(
            f"/projects/{project_id}/export-with-secrets",
            data={"export_format": "markdown"},
        )
        assert missing_confirmation.status_code == 400

        sensitive_markdown = client.post(
            f"/projects/{project_id}/export-with-secrets", data=sensitive_payload
        )
        assert sensitive_markdown.status_code == 200
        assert SAVED_SECRET in sensitive_markdown.text
        assert "-sensitive.md" in sensitive_markdown.headers["content-disposition"]
        assert sensitive_markdown.headers["cache-control"].startswith("no-store")

        sensitive_pdf = client.post(
            f"/projects/{project_id}/export-with-secrets",
            data={"export_format": "pdf", "confirm_sensitive_export": "true"},
        )
        assert sensitive_pdf.status_code == 200
        pdf_args, pdf_kwargs = observed_pdf_calls[-1]
        assert pdf_kwargs["include_secrets"] is True
        assert pdf_args[5][0]["secret_value"] == SAVED_SECRET

        disable_response = client.post("/settings/vault/export-policy", data={})
        assert disable_response.status_code == 303
        blocked_after_disable = client.post(
            f"/projects/{project_id}/export-with-secrets", data=sensitive_payload
        )
        assert blocked_after_disable.status_code == 403


def test_master_password_setup_requires_matching_long_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "vault-validation.db"))

    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        too_short = client.post(
            "/settings/vault/setup",
            data={"master_password": "short", "confirm_password": "short"},
        )
        assert too_short.status_code == 400

        mismatch = client.post(
            "/settings/vault/setup",
            data={"master_password": MASTER_PASSWORD, "confirm_password": "different phrase"},
        )
        assert mismatch.status_code == 400


def test_markdown_html_is_sanitized_before_rendering() -> None:
    from app.presentation import markdown_filter

    rendered = markdown_filter(
        '<script>fetch("/accounts/1/reveal")</script>\n\n'
        '<img src="x" onerror="alert(1)">\n\n'
        '[unsafe](javascript:alert(1))\n\n'
        "```python\nprint('<still code>')\n```"
    )

    assert "<script" not in rendered.lower()
    assert "onerror" not in rendered.lower()
    assert 'href="javascript:' not in rendered.lower()
    assert "<pre><code" in rendered
    assert "&lt;still code&gt;" in rendered
