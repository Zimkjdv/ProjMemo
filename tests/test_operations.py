"""Secret-safe diagnostics and read-only probes, always on isolated databases."""

import asyncio
from pathlib import Path
import re
import sqlite3
import traceback
from types import SimpleNamespace

from fastapi.testclient import TestClient as RawTestClient
import pytest

from app import main, operations
from app.database_access import access_for
from app.db import MigrationError
from tests.client import TestClient

SENTINEL = "r07-fixture-password-that-must-not-leak"


def test_probes_before_startup_do_not_create_database_or_directories(tmp_path, monkeypatch):
    path = tmp_path / "absent" / "never-created.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    client = RawTestClient(main.create_app(), base_url="http://127.0.0.1")
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 503
    assert not path.parent.exists()
    client.close()


def test_ready_is_read_only_minimal_and_log_handles_close(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    application = main.create_app()
    with TestClient(application) as client:
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        for endpoint, value in [("live", "alive"), ("ready", "ready")]:
            response = client.get("/health/" + endpoint)
            assert response.status_code == 200
            assert response.json() == {"status": value}
            assert "no-store" in response.headers["cache-control"]
            assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
        assert "/health/live" not in application.openapi()["paths"]
        assert client.get("/health/live", headers={"Host": "evil.invalid"}).status_code == 400
    assert application.state.operations_logger is None
    assert not application.state.startup_ready
    log = tmp_path / "logs/projmemo.log"
    assert "startup_ready" in log.read_text()
    assert "shutdown_complete" in log.read_text()
    log.rename(tmp_path / "closed-log.txt")  # Windows would reject a leaked handler.


@pytest.mark.parametrize("unavailable", ["maintenance", "recovery", "missing", "corrupt", "version", "space"])
def test_liveness_survives_database_unavailability(tmp_path, monkeypatch, unavailable):
    path = tmp_path / "fixture.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    with TestClient(main.create_app()) as client:
        access = access_for(path)
        if unavailable == "maintenance":
            with access.maintenance():
                assert client.get("/health/live").status_code == 200
                assert client.get("/health/ready").status_code == 503
            assert client.get("/health/ready").status_code == 200
            return
        if unavailable == "recovery":
            access.require_recovery()
        elif unavailable == "missing":
            path.unlink()
        elif unavailable == "corrupt":
            path.write_bytes(SENTINEL.encode())
        elif unavailable == "version":
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version=999")
        else:
            monkeypatch.setattr(operations.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
        response = client.get("/health/ready")
        assert response.status_code == 503 and response.json() == {"status": "not_ready"}
        assert client.get("/health/live").status_code == 200
        assert SENTINEL not in response.text
        if unavailable == "missing":
            assert not path.exists()


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("exception,status,category", [
    (ValueError, 500, "INTERNAL_ERROR"), (sqlite3.OperationalError, 503, "DATABASE_ERROR"),
    (PermissionError, 503, "STORAGE_ERROR"),
])
def test_exception_log_and_response_exclude_all_request_values(tmp_path, monkeypatch, language, exception, status, category):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "fixture.db"))
    application = main.create_app()

    @application.post("/fixture/error/{identifier}")
    def fail(identifier: str):
        raise exception(SENTINEL)

    with TestClient(application) as client:
        client.cookies.set("projmemo_language", language)
        client.cookies.set("fixture_sensitive_cookie", SENTINEL)
        response = client.post(f"/fixture/error/{SENTINEL}?password={SENTINEL}",
            data={"secret_value": SENTINEL, "username": SENTINEL},
            headers={"X-Request-ID": SENTINEL, "Authorization": "Bearer " + SENTINEL})
        assert response.status_code == status
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert re.fullmatch(r"[0-9a-f]{32}", response.json()["request_id"])
        if language == "en":
            assert "temporarily unavailable" in response.text
        assert SENTINEL not in response.text
        log = (tmp_path / "logs/projmemo.log").read_text()
        assert category in log and "route=/fixture/error/{identifier}" in log
        assert response.headers["x-request-id"] in log
        assert SENTINEL not in log and "Traceback" not in log


@pytest.mark.parametrize("failure,code", [("space", "DATA_SPACE_LOW"), ("permission", "DATA_DIRECTORY_UNWRITABLE"),
                                        ("schema", "DATABASE_RECOVERY_REQUIRED")])
def test_startup_failure_has_safe_actionable_code_and_no_database_loss(tmp_path, monkeypatch, failure, code):
    path = tmp_path / "existing.db"
    path.write_bytes(b"unchanged fixture database")
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    if failure == "space":
        monkeypatch.setattr(operations.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    elif failure == "permission":
        monkeypatch.setattr(operations.tempfile, "mkstemp", lambda **_: (_ for _ in ()).throw(PermissionError(SENTINEL)))
    else:
        monkeypatch.setattr(main, "init_db", lambda: (_ for _ in ()).throw(
            MigrationError(SENTINEL, snapshot_path=tmp_path / SENTINEL, recovered=False)))
    with pytest.raises(MigrationError if failure == "schema" else RuntimeError, match=code) as caught:
        with TestClient(main.create_app()):
            pass
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))
    assert path.read_bytes() == b"unchanged fixture database"
    assert not list(tmp_path.glob(".projmemo-write-probe-*"))
    if failure == "schema":
        assert SENTINEL not in (tmp_path / "logs/projmemo.log").read_text()


def test_log_rotation_is_bounded_and_log_failure_has_no_traceback(tmp_path, monkeypatch, capsys):
    original = operations.SafeRotatingHandler
    monkeypatch.setattr(operations, "SafeRotatingHandler", lambda filename, **_: original(filename, maxBytes=300, backupCount=3, encoding="utf-8"))
    with operations.operational_log(tmp_path / "fixture.db") as logger:
        for _ in range(50):
            logger.error("request_failed id=fixture method=GET route=unmatched status=500 category=INTERNAL_ERROR")
    files = list((tmp_path / "logs").glob("projmemo.log*"))
    assert len(files) == 4
    handler = original(tmp_path / "failure.log", maxBytes=1, backupCount=1)
    try:
        monkeypatch.setattr(handler, "shouldRollover", lambda _: True)
        monkeypatch.setattr(handler, "doRollover", lambda: (_ for _ in ()).throw(OSError(SENTINEL)))
        import logging
        handler.emit(logging.LogRecord("fixture", logging.ERROR, "", 0, "safe event", (), None))
    finally:
        handler.close()
    output = capsys.readouterr().err
    assert "LOG_WRITE_FAILED" in output
    assert SENTINEL not in output and "Traceback" not in output


@pytest.mark.parametrize("blocked", ["database_path", "logs"])
def test_invalid_data_or_log_directory_refuses_startup_without_deleting_files(tmp_path, monkeypatch, blocked):
    path = tmp_path / "fixture.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    if blocked == "database_path":
        path.mkdir()
        marker = path / "keep.txt"
        marker.write_text(SENTINEL)
        code = "DATA_PATH_INVALID"
    else:
        marker = tmp_path / "logs"
        marker.write_text(SENTINEL)
        code = "STORAGE_ERROR"
    with pytest.raises(RuntimeError, match=code) as caught:
        with TestClient(main.create_app()):
            pass
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))
    assert marker.read_text() == SENTINEL


def test_partial_response_failure_is_sanitized_and_not_sent_twice(caplog):
    sent = []

    async def broken(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError(SENTINEL)

    async def send(message):
        sent.append(message)

    with pytest.raises(RuntimeError, match="response stream failed") as caught:
        asyncio.run(operations.SafeDiagnosticsMiddleware(broken)({"type": "http", "method": "GET"}, None, send))
    assert len(sent) == 1
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))
    assert SENTINEL not in caplog.text and "request_failed" in caplog.text
