from html.parser import HTMLParser
from pathlib import Path
import json
import sqlite3

import pytest

from tests.client import TestClient


class BackupMarkup(HTMLParser):
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
            self.current_form = {"attrs": attributes, "inputs": []}
            self.forms[attributes["action"]] = self.current_form
        elif tag == "input" and self.current_form is not None:
            self.current_form["inputs"].append(attributes)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("state", ["empty", "populated", "success", "error", "unavailable"])
def test_backup_ui_preserves_restore_confirmation_and_recovery_access(tmp_path: Path, monkeypatch, language, state):
    database = tmp_path / "backup-ui.sqlite3"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(database))
    from app.main import app
    from app.backup import BackupRestoreError, create_database_backup, recovery_directory
    from app.database_access import DatabaseBusyError
    from app.i18n import translate

    with TestClient(app, follow_redirects=False) as client:
        project_count = 0 if state == "empty" else 250 if state == "populated" else 1
        with sqlite3.connect(database) as connection:
            connection.executemany("INSERT INTO projects (name) VALUES (?)", [(f"UI fixture {index}",) for index in range(project_count)])
        snapshots = []
        if state != "empty":
            directory = recovery_directory(database)
            directory.mkdir()
            for index in range(11 if state == "populated" else 1):
                snapshot = directory / f"projmemo-pre-restore-20261013-090000-{index:06d}.sqlite3"
                create_database_backup(database, snapshot)
                snapshots.append(snapshot)
        assert client.post("/settings/language", data={"language": language}).status_code == 303

        if state == "error":
            def failed_restore(*args, **kwargs):
                raise BackupRestoreError("還原失敗，且自動回復未能完成。請保留並下載還原前備份。", snapshots[0].name, False)
            monkeypatch.setattr("app.services.backups.restore_database", failed_restore)
            response = client.post("/settings/backup/restore", files={"backup_file": ("fixture.sqlite3", database.read_bytes())})
            assert response.status_code == 500
        else:
            if state == "unavailable":
                def unavailable_database():
                    raise DatabaseBusyError("UI fixture database unavailable")
                monkeypatch.setattr("app.services.backups.db_session", unavailable_database)
            url = f"/settings/backup?restored=true&recovery={snapshots[0].name}" if state == "success" else "/settings/backup"
            response = client.get(url)
            assert response.status_code == 200

        page = BackupMarkup(response.text)
        ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        assert {"backup-title", "backup-download-title", "backup-restore-title", "backup-guidance-title", "backup-history-title"}.issubset(ids)
        navigation = "主要導覽" if language == "zh-Hant" else "Main navigation"
        assert any(tag == "nav" and attrs.get("aria-label") == navigation for tag, attrs in page.elements)
        assert any(tag == "a" and attrs.get("href") == "/settings/backup/download" for tag, attrs in page.elements)
        assert "100 MB" in response.text

        form = page.forms["/settings/backup/restore"]
        assert form["attrs"]["method"] == "post"
        assert form["attrs"]["enctype"] == "multipart/form-data"
        assert "return confirm(" in form["attrs"]["onsubmit"]
        confirmation = json.loads(form["attrs"]["onsubmit"].removeprefix("return confirm(").removesuffix(")"))
        assert confirmation == translate("確定以所選備份取代目前所有專案資料？系統會先自動保存目前資料。", language)
        assert any(field.get("name") == "csrf_token" and field.get("value") for field in form["inputs"])
        upload = next(field for field in form["inputs"] if field.get("name") == "backup_file")
        assert upload["type"] == "file" and "required" in upload
        assert upload["accept"] == ".sqlite3,.sqlite,.db,application/vnd.sqlite3"
        assert upload["aria-describedby"] in ids
        assert not upload.get("value")
        assert any(tag == "button" and "button-danger" in attrs.get("class", "").split() for tag, attrs in page.elements)

        recovery_links = {attrs["href"] for tag, attrs in page.elements if tag == "a" and attrs.get("href", "").startswith("/settings/backup/files/")}
        assert len(recovery_links) == min(len(snapshots), 10)
        assert all(href.rsplit("/", 1)[1] in {path.name for path in snapshots} for href in recovery_links)
        if state in {"success", "error"}:
            role = "status" if state == "success" else "alert"
            assert any(attrs.get("role") == role for _, attrs in page.elements)
        for href in recovery_links:
            download = client.get(href)
            assert download.status_code == 200
            assert download.content.startswith(b"SQLite format 3\x00")
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == project_count
