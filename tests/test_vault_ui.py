from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.client import TestClient


MASTER_PASSWORD = "vault UI fixture master phrase"


class VaultPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.forms = {}
        self.current_form = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "form":
            self.current_form = {"attrs": attributes, "inputs": [], "buttons": []}
            self.forms[attributes["action"]] = self.current_form
        elif tag == "input" and self.current_form is not None:
            self.current_form["inputs"].append(attributes)
        elif tag == "button" and self.current_form is not None:
            self.current_form["buttons"].append(attributes)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("state", ["setup", "locked", "unlocked", "sensitive", "locked-sensitive"])
def test_vault_ui_preserves_state_forms_and_security_contract(tmp_path: Path, monkeypatch, language, state):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "vault-ui.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        if state != "setup":
            assert client.post("/settings/vault/setup", data={
                "master_password": MASTER_PASSWORD, "confirm_password": MASTER_PASSWORD,
            }).status_code == 303
        if "sensitive" in state:
            assert client.post("/settings/vault/export-policy", data={"allow_secret_export": "true"}).status_code == 303
        if state.startswith("locked"):
            assert client.post("/settings/vault/lock").status_code == 303
        assert client.post("/settings/language", data={"language": language}).status_code == 303

        response = client.get("/settings/vault")
        assert response.status_code == 200
        assert "no-store" in {directive.strip() for directive in response.headers["cache-control"].split(",")}
        assert MASTER_PASSWORD not in response.text
        page = VaultPage(response.text)
        assert not any(tag == "nav" and "breadcrumb" in attrs.get("class", "").split() for tag, attrs in page.elements)
        main_navigation = "主要導覽" if language == "zh-Hant" else "Main navigation"
        assert any(tag == "nav" and attrs.get("aria-label") == main_navigation for tag, attrs in page.elements)
        visible_state = "setup" if state == "setup" else "locked" if state.startswith("locked") else "unlocked"
        assert any(attrs.get("data-vault-state") == visible_state for _, attrs in page.elements)
        badges = [attrs for _, attrs in page.elements if "data-vault-state-label" in attrs]
        assert len(badges) == 1 and "data-vault-state-short" in badges[0]
        assert any(tag == "a" and attrs.get("href") == "/settings/vault" and attrs.get("aria-current") == "page" for tag, attrs in page.elements)
        assert sum(tag == "dd" for tag, _ in page.elements) == 4
        assert "Argon2id" in response.text and "AES-GCM" in response.text
        assert any("vault-rule-critical" in attrs.get("class", "").split() for _, attrs in page.elements)
        timers = [attrs for _, attrs in page.elements if "data-vault-countdown" in attrs]
        assert len(timers) == int(visible_state == "unlocked")
        if timers:
            assert timers[0]["role"] == "timer" and timers[0]["aria-live"] == "off"
            progress = next(attrs for tag, attrs in page.elements if tag == "progress")
            assert progress["max"] == "900" and 0 < float(progress["value"]) <= 900
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        assert {"vault-title", "vault-access-title", "vault-export-title", "vault-notice-title"}.issubset(ids)
        local_reminder = "僅限本機使用" if language == "zh-Hant" else "Local use only"
        reset_reminder = "主密碼無法重設" if language == "zh-Hant" else "No master password reset"
        assert local_reminder in response.text
        assert reset_reminder in response.text

        operation = "setup" if state == "setup" else "unlock" if state.startswith("locked") else "lock"
        vault_actions = {action for action in page.forms if action.startswith("/settings/vault/")}
        expected_actions = {f"/settings/vault/{operation}"}
        if state != "setup":
            expected_actions.add("/settings/vault/export-policy")
            expected_actions.add("/settings/vault/change-password")
        assert vault_actions == expected_actions
        for action in vault_actions:
            form = page.forms[action]
            assert form["attrs"]["method"] == "post"
            assert any(field.get("name") == "csrf_token" and field.get("value") for field in form["inputs"])

        passwords = [attrs for tag, attrs in page.elements if tag == "input" and attrs.get("type") == "password"]
        assert len(passwords) == (2 if state == "setup" else 4 if state.startswith("locked") else 3)
        for field in passwords:
            assert not field.get("value")
            assert "required" in field
            assert field["maxlength"] == "1024"
            new_password = state == "setup" or field["name"] in {"new_master_password", "confirm_new_password"}
            assert field["autocomplete"] == ("new-password" if new_password else "current-password")
            if new_password:
                assert field["minlength"] == "16"
        if state != "setup":
            policy = next(field for field in page.forms["/settings/vault/export-policy"]["inputs"] if field.get("name") == "allow_secret_export")
            assert policy["type"] == "checkbox"
            assert policy["role"] == "switch" and policy.get("aria-describedby")
            assert ("checked" in policy) == ("sensitive" in state)
            assert "disabled" not in policy  # A locked vault must still allow disabling sensitive exports.
            save = page.forms["/settings/vault/export-policy"]["buttons"][0]
            assert save["class"] == "button button-primary"
            assert "disabled" not in save  # Native forms remain usable without JavaScript.


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_vault_validation_error_stays_visible_without_refilling_passwords(tmp_path: Path, monkeypatch, language):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "vault-ui-errors.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        client.post("/settings/language", data={"language": language})
        response = client.post("/settings/vault/setup", data={
            "master_password": MASTER_PASSWORD, "confirm_password": "different fixture phrase",
        })
        assert response.status_code == 400
        assert MASTER_PASSWORD not in response.text
        page = VaultPage(response.text)
        assert any(attrs.get("role") == "alert" for _, attrs in page.elements)
        assert all(not attrs.get("value") for tag, attrs in page.elements if tag == "input" and attrs.get("type") == "password")
