from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pytest

from tests.client import TestClient


class AccountElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("state", ["setup", "locked", "unlocked", "locked-sensitive", "unlocked-sensitive"])
def test_account_copy_targets_and_vault_states_preserve_protection(tmp_path: Path, monkeypatch, language, state):
    from app.main import app

    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "account-ui.db"))
    with TestClient(app, follow_redirects=False) as client:
        project = client.post("/projects/new", data={"name": "Account fixture"}).headers["location"]
        client.post("/settings/language", data={"language": language})
        password = "account UI fixture master phrase"
        if state != "setup":
            client.post("/settings/vault/setup", data={"master_password": password, "confirm_password": password})
        if "sensitive" in state:
            client.post("/settings/vault/export-policy", data={"allow_secret_export": "true"})
        client.post(f"{project}/urls", data={"title": "Long URL", "type": "git", "url": "https://example.invalid/" + "long-path/" * 40})
        for label, data in [
            ("Saved", {"secret_value": "fixture-secret-never-in-html"} if state != "setup" else {}),
            ("External", {"secret_reference": "External fixture vault"}),
            ("Empty", {}),
        ]:
            client.post(f"{project}/accounts", data={"label": label, "category": "server", "endpoint": 'host.example.invalid:2222',
                                                     "username": 'fixture <literal> "quoted"', **data})
        if state.startswith("locked"):
            client.post("/settings/vault/lock")
        page = client.get(project)
        assert page.status_code == 200
        assert password not in page.text and "fixture-secret-never-in-html" not in page.text
        assert "15 分鐘後自動鎖定" not in page.text
        elements = AccountElements(page.text).elements
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        targets = [attrs["data-copy-target"] for _, attrs in elements if "data-copy-target" in attrs]
        assert len(targets) == 7  # One URL and two fields for each account; no password target.
        for target in targets:
            assert target in ids and not target.startswith("secret")
            tag, attrs = next((tag, attrs) for tag, attrs in elements if attrs.get("id") == target)
            assert tag == "code" and "data-copy-value" in attrs
        assert 'fixture &lt;literal&gt; &#34;quoted&#34;' in page.text
        assert any("data-vault-session" in attrs for _, attrs in elements)
        saved = any(attrs.get("data-secret-state") == "saved" for _, attrs in elements)
        assert saved == (state != "setup")
        assert any(attrs.get("data-secret-state") == "external" for _, attrs in elements)
        assert any(attrs.get("data-secret-state") == "empty" for _, attrs in elements)
        status = json.loads(re.search(r'id="vault-session-state">(.*?)</script>', page.text, re.S)[1])["status"]
        assert status["unlocked"] == state.startswith("unlocked")
        if state == "unlocked-sensitive":
            assert 'action="' + project + '/export-with-secrets"' in page.text
            assert 'name="confirm_sensitive_export" value="true" required' in page.text
        else:
            assert f'action="{project}/export-with-secrets"' not in page.text
        assert all(not attrs.get("value") for tag, attrs in elements if tag == "input" and attrs.get("type") == "password")
