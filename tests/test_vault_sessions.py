import json
from pathlib import Path
import re

from app.vault import VaultSessions
from tests.client import TestClient


def test_sessions_expire_without_renewal_and_sweep_all_tokens():
    now = [100.0]
    sessions = VaultSessions(ttl_seconds=10, clock=lambda: now[0], wall_clock=lambda: 5000)
    first = sessions.issue(b"a" * 32)
    second = sessions.issue(b"b" * 32)
    now[0] = 106
    status = sessions.status(first)
    assert status["remaining_seconds"] == 4
    assert status["expires_at_ms"] == 5004000
    assert "key" not in status and "token" not in status
    assert sessions.get_key(first) == b"a" * 32
    now[0] = 110
    assert sessions.purge_expired() == 2
    assert sessions.get_key(first) is None and sessions.get_key(second) is None
    assert sessions.status(first)["unlocked"] is False


def test_reissue_reclaims_previous_session_and_capacity_is_bounded():
    now = [0.0]
    sessions = VaultSessions(max_sessions=2, clock=lambda: now[0])
    first = sessions.issue(b"a" * 32)
    first_version = sessions.status(first)["session_version"]
    now[0] += 1
    replacement = sessions.issue(b"b" * 32, replace_token=first)
    assert sessions.get_key(first) is None
    assert sessions.status(replacement)["session_version"] != first_version
    now[0] += 1
    second = sessions.issue(b"c" * 32)
    now[0] += 1
    third = sessions.issue(b"d" * 32)
    assert sessions.get_key(replacement) is None
    assert sessions.get_key(second) is not None and sessions.get_key(third) is not None
    sessions.revoke(second)
    assert sessions.get_key(second) is None
    sessions.clear()
    assert sessions.get_key(third) is None


def test_status_and_html_use_current_remaining_time_and_expired_requests_fail(tmp_path: Path, monkeypatch):
    import app.main as main

    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "sessions.db"))
    now = [0.0]
    sessions = VaultSessions(clock=lambda: now[0], wall_clock=lambda: 5000)
    monkeypatch.setattr(main, "vault_sessions", sessions)
    with TestClient(main.app, follow_redirects=False) as client:
        project = client.post("/projects/new", data={"name": "Session fixture"}).headers["location"]
        password = "fixture master phrase for sessions"
        client.post("/settings/vault/setup", data={"master_password": password, "confirm_password": password})
        old_token = client.cookies.get("projmemo_vault")
        client.post(f"{project}/accounts", data={"label": "Encrypted fixture", "secret_value": "fixture-only-secret"})
        now[0] = 120
        response = client.get("/settings/vault/status")
        assert "no-store" in response.headers["cache-control"]
        assert response.json()["remaining_seconds"] == 780
        assert old_token not in response.text and password not in response.text
        for url in (project, "/settings/vault"):
            page = client.get(url)
            state = json.loads(re.search(r'id="vault-session-state">(.*?)</script>', page.text, re.S)[1])
            assert state["status"]["remaining_seconds"] == 780
            assert "fixture-only-secret" not in page.text
        client.post("/settings/vault/unlock", data={"master_password": password})
        assert sessions.get_key(old_token) is None
        assert client.get("/settings/vault/status").json()["remaining_seconds"] == 900
        now[0] = 1020
        assert client.get("/settings/vault/status").json()["unlocked"] is False
        assert client.post("/accounts/1/reveal").status_code == 423
        client.post("/settings/vault/unlock", data={"master_password": password})
        client.post("/settings/vault/lock")
        assert client.get("/settings/vault/status").json()["unlocked"] is False


def test_expiry_during_decryption_does_not_return_plaintext(tmp_path: Path, monkeypatch):
    import app.main as main

    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "pending.db"))
    now = [0.0]
    monkeypatch.setattr(main, "vault_sessions", VaultSessions(ttl_seconds=10, clock=lambda: now[0]))
    decrypt = main.decrypt_secret
    def expire_after_decrypt(*args):
        result = decrypt(*args)
        now[0] = 10
        return result
    monkeypatch.setattr(main, "decrypt_secret", expire_after_decrypt)
    with TestClient(main.app, follow_redirects=False) as client:
        project = client.post("/projects/new", data={"name": "Pending fixture"}).headers["location"]
        password = "fixture master phrase for delayed response"
        client.post("/settings/vault/setup", data={"master_password": password, "confirm_password": password})
        client.post(f"{project}/accounts", data={"label": "Pending", "secret_value": "must-not-return"})
        response = client.post("/accounts/1/reveal")
        assert response.status_code == 423 and "must-not-return" not in response.text
