from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3

from fastapi.testclient import TestClient as RawTestClient
import pytest

from app.web_security import CSRF_COOKIE, new_csrf_token


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "security.sqlite3"))
    from app.main import app
    with RawTestClient(app, base_url="http://127.0.0.1:8123", follow_redirects=False) as client:
        yield client


def token(client):
    page = client.get("/projects/new")
    assert page.status_code == 200
    value = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    assert value == client.cookies.get(CSRF_COOKIE)
    return value


def test_native_form_and_header_workflows_require_signed_matching_tokens(client):
    assert client.post("/projects/new", data={"name": "blocked"}).status_code == 403
    csrf = token(client)
    cookie = client.get("/").headers.get("set-cookie", "")
    assert not cookie  # Existing valid browser token is not rotated per request.
    created = client.post("/projects/new", data={"name": "native form", "csrf_token": csrf},
                          headers={"Origin": "http://127.0.0.1:8123", "Sec-Fetch-Site": "same-origin"})
    assert created.status_code == 303
    assert client.post("/projects/1/edit", data={"name": "missing token"}).status_code == 403
    for invalid in ("forged", "錯誤", csrf[:-1] + ("0" if csrf[-1] != "0" else "1"), new_csrf_token()):
        assert client.post("/projects/1/edit", data={"name": "invalid", "csrf_token": invalid}).status_code == 403
    assert client.post("/projects/1/edit", data={"name": "header action"},
                       headers={"X-CSRF-Token": csrf}).status_code == 303
    assert "header action" in client.get("/").text
    client.cookies.set(CSRF_COOKIE, "unsigned-cookie", domain="127.0.0.1", path="/")
    assert client.post("/projects/1/edit", data={"name": "invalid cookie"},
                       headers={"X-CSRF-Token": "unsigned-cookie"}).status_code == 403


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "http://127.0.0.1:8124"},
    {"Origin": "http://localhost:8123"},
    {"Origin": "null"},
    {"Origin": "http://[broken"},
    {"Origin": "http://127.0.0.1:8123/path"},
    {"Origin": "http://127.0.0.1:8123.evil.example"},
    {"Referer": "https://evil.example/form"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_bad_sources_cannot_mutate_even_with_a_valid_token(client, headers):
    csrf = token(client)
    response = client.post("/projects/new", data={"name": "must not exist", "csrf_token": csrf}, headers=headers)
    assert response.status_code == 403
    assert "must not exist" not in client.get("/").text


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "192.168.1.5:8123",
                                  "127.0.0.1:0", "127.0.0.1:99999", "user@localhost", "localhost/path"])
def test_bad_host_rejected_before_routes(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("base", ["http://127.0.0.1:8001", "http://localhost:8123"])
def test_local_hosts_dynamic_ports_and_language_switch(tmp_path, monkeypatch, base):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "ports.sqlite3"))
    from app.main import app
    with RawTestClient(app, base_url=base, follow_redirects=False) as client:
        csrf = token(client)
        assert client.post("/settings/language", data={"language": "en", "csrf_token": csrf},
                           headers={"Origin": base}).status_code == 303
        denied = client.post("/projects/new", data={"name": "blocked"})
        assert denied.status_code == 403
        assert "Refresh the page" in denied.json()["detail"]
        assert "New project" in client.get("/projects/new").text


def test_ipv6_host_and_origin_with_current_test_transport(client):
    # Starlette 0.46's TestClient cannot parse an IPv6 base_url. Exercise the
    # same ASGI Host/Origin headers without modifying the production whitelist.
    client.headers["Host"] = "[::1]:8124"
    csrf = token(client)
    response = client.post("/projects/new", data={"name": "IPv6 host", "csrf_token": csrf},
                           headers={"Origin": "http://[::1]:8124"})
    assert response.status_code == 303


def test_missing_tokens_block_every_existing_post_route(client):
    from app.main import app
    token(client)
    for route in app.routes:
        if "POST" not in (getattr(route, "methods", None) or set()):
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        response = client.post(path, data={"name": "blocked"})
        assert response.status_code == 403, path


class FormTokens(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"method": attrs.get("method"), "tokens": []}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and attrs.get("name") == "csrf_token":
            self.current["tokens"].append(attrs.get("value"))

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def test_all_rendered_post_forms_include_tokens_without_javascript(client):
    csrf = token(client)
    headers = {"X-CSRF-Token": csrf}
    assert client.post("/projects/new", data={"name": "form coverage"}, headers=headers).status_code == 303
    fixtures = [
        ("urls", {"title": "URL", "url": "https://example.com"}),
        ("notes", {"title": "note", "content_markdown": "safe note"}),
        ("checklist", {"title": "handover"}),
        ("environment-variables", {"key": "EXAMPLE"}),
        ("accounts", {"label": "test account"}),
    ]
    for suffix, data in fixtures:
        assert client.post(f"/projects/1/{suffix}", data=data, headers=headers).status_code == 303
    # Setup and unlock states produce different forms; sensitive export also needs coverage.
    pages = [client.get("/settings/vault").text]
    assert client.post("/settings/vault/setup", data={"master_password": "test-only-master-password",
                       "confirm_password": "test-only-master-password"}, headers=headers).status_code == 303
    assert client.post("/settings/vault/export-policy", data={"allow_secret_export": "true"}, headers=headers).status_code == 303
    pages += [client.get(path).text for path in ("/", "/projects/new", "/projects/1/edit", "/projects/1",
                                                "/settings/vault", "/settings/backup")]
    assert client.post("/settings/vault/lock", headers=headers).status_code == 303
    pages.append(client.get("/settings/vault").text)
    count = 0
    for page in pages:
        parser = FormTokens()
        parser.feed(page)
        for form in parser.forms:
            if form["method"] == "post":
                assert form["tokens"] == [csrf]
                count += 1
    assert count >= 25


def test_multipart_restore_without_csrf_is_blocked_and_valid_native_form_works(client, tmp_path):
    csrf = token(client)
    created = client.post("/projects/new", data={"name": "original", "csrf_token": csrf})
    assert created.status_code == 303
    snapshot = client.get("/settings/backup/download")
    for name, value in (("cache-control", "no-store"), ("x-content-type-options", "nosniff")):
        assert value in snapshot.headers[name]
    upload = {"backup_file": ("backup.sqlite3", snapshot.content)}
    assert client.post("/settings/backup/restore", files=upload).status_code == 403
    restored = client.post("/settings/backup/restore", files=upload, data={"csrf_token": csrf})
    assert restored.status_code == 303
    from app.db import database_path
    recovery = next((database_path().parent / "backups").glob("*.sqlite3"))
    response = client.get(f"/settings/backup/files/{recovery.name}")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"


def test_cookie_attributes_and_restart_invalidates_old_tokens(client, monkeypatch):
    response = client.get("/")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    csrf = client.cookies.get(CSRF_COOKIE)
    monkeypatch.setattr("app.web_security._SIGNING_KEY", b"y" * 32)
    denied = client.post("/projects/new", data={"name": "stale page", "csrf_token": csrf})
    assert denied.status_code == 403
    new_token = token(client)
    assert new_token != csrf
    assert client.post("/projects/new", data={"name": "fresh page", "csrf_token": new_token}).status_code == 303


def test_https_cookie_is_secure_and_duplicate_form_tokens_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "https.sqlite3"))
    from app.main import app
    with RawTestClient(app, base_url="https://localhost:8123", follow_redirects=False) as client:
        response = client.get("/projects/new")
        assert "Secure" in response.headers["set-cookie"]
        csrf = client.cookies.get(CSRF_COOKIE)
        assert client.post("/projects/new", data={"name": "duplicate tokens", "csrf_token": [csrf, csrf]}).status_code == 403
        assert client.post("/projects/new", data={"name": "HTTPS form", "csrf_token": csrf},
                           headers={"Origin": "https://localhost:8123"}).status_code == 303


def test_invalid_host_and_cookie_rejected_without_consuming_request_body():
    import asyncio
    from app.web_security import LocalRequestSecurityMiddleware

    async def run():
        async def forbidden(*args):
            pytest.fail("Rejected requests must not parse a body or enter routes")
        for headers, expected in (([(b"host", b"localhost"), (b"host", b"evil.example")], 400),
                                  ([(b"host", b"localhost")], 403)):
            sent = []
            async def send(message):
                sent.append(message)
            scope = {"type": "http", "scheme": "http", "method": "POST", "path": "/settings/backup/restore",
                     "query_string": b"", "headers": headers, "server": ("localhost", 80)}
            await LocalRequestSecurityMiddleware(forbidden)(scope, forbidden, send)
            assert sent[0]["status"] == expected
    asyncio.run(run())


def test_html_policy_preserves_native_form_origins_and_download_privacy(client):
    csrf = token(client)
    assert client.post("/projects/new", data={"name": "policy fixture", "csrf_token": csrf}).status_code == 303
    for path in ("/", "/projects/new", "/projects/1", "/projects/1/edit", "/settings/vault", "/settings/backup"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert page.headers["referrer-policy"] == "same-origin", path
        assert '<meta name="referrer" content="same-origin">' in page.text, path
        assert '<meta name="referrer" content="no-referrer">' not in page.text, path
        assert "no-store" in page.headers["cache-control"]
    download = client.get("/settings/backup/download")
    assert download.headers["referrer-policy"] == "no-referrer"
    rejected = client.post("/settings/language", data={"language": "en", "csrf_token": csrf},
                           headers={"Origin": "null"})
    assert rejected.status_code == 403


def test_language_switch_after_same_origin_page_preserves_return_path(client):
    csrf = token(client)
    destination = "/?view=list&page_size=20&q=fixture#home-intro-title"
    for language in ("en", "zh-Hant"):
        switched = client.post("/settings/language",
                               data={"language": language, "return_to": destination, "csrf_token": csrf},
                               headers={"Origin": "http://127.0.0.1:8123", "Sec-Fetch-Site": "same-origin"})
        assert switched.status_code == 303
        assert switched.headers["location"] == destination
        assert client.get(destination).headers["referrer-policy"] == "same-origin"
        assert f'<html lang="{language}">' in client.get(destination).text
