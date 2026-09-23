from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient


def test_project_lifecycle(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "test.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(database_path))

    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        response = client.post(
            "/projects/new",
            data={
                "name": "測試專案",
                "description": "專案描述",
                "status": "maintenance",
                "owner": "Codex",
                "tags": "Python, API",
            },
        )
        assert response.status_code == 303
        project_url = response.headers["location"]

        response = client.post(
            f"{project_url}/urls",
            data={"type": "git", "title": "GitHub", "url": "https://github.com/example/repo"},
        )
        assert response.status_code == 303

        response = client.post(
            f"{project_url}/notes",
            data={
                "category": "known_issue",
                "title": "已知問題",
                "content_markdown": "使用 `--reload` 啟動。",
                "priority": "high",
            },
        )
        assert response.status_code == 303

        response = client.post(
            f"{project_url}/checklist",
            data={
                "category": "deployment",
                "title": "確認部署步驟",
                "description": "執行部署檢查。",
            },
        )
        assert response.status_code == 303

        response = client.get(project_url)
        assert response.status_code == 200
        assert "測試專案" in response.text
        assert "已知問題" in response.text
        assert "確認部署步驟" in response.text

        response = client.get(f"{project_url}/export.md")
        assert response.status_code == 200
        assert "# 測試專案" in response.text
        assert "GitHub" in response.text

        monkeypatch.setattr("app.main.generate_project_pdf", lambda *_: b"%PDF-1.4\nmock")
        response = client.get(f"{project_url}/export.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")

        backup_page = client.get("/settings/backup")
        assert backup_page.status_code == 200
        assert "資料備份與還原" in backup_page.text
        backup_response = client.get("/settings/backup/download")
        assert backup_response.status_code == 200
        assert backup_response.content.startswith(b"SQLite format 3\x00")
        backup_path = tmp_path / "projmemo-test.sqlite3"
        backup_path.write_bytes(backup_response.content)
        with sqlite3.connect(backup_path) as backup_connection:
            backed_up_name = backup_connection.execute(
                "SELECT name FROM projects WHERE name = ?", ("測試專案",)
            ).fetchone()
            assert backed_up_name == ("測試專案",)

        response = client.post(
            "/projects/new",
            data={
                "name": "還原後應消失的專案",
                "description": "用來驗證備份還原",
                "status": "maintenance",
            },
        )
        assert response.status_code == 303

        invalid_response = client.post(
            "/settings/backup/restore",
            files={"backup_file": ("invalid.sqlite3", b"not a database", "application/octet-stream")},
        )
        assert invalid_response.status_code == 400
        assert "不是有效的 SQLite" in invalid_response.text
        assert "還原後應消失的專案" in client.get("/").text

        empty_database_path = tmp_path / "empty.sqlite3"
        with sqlite3.connect(empty_database_path) as empty_connection:
            empty_connection.execute("CREATE TABLE unrelated (id INTEGER)")
        incompatible_response = client.post(
            "/settings/backup/restore",
            files={
                "backup_file": (
                    "empty.sqlite3",
                    empty_database_path.read_bytes(),
                    "application/vnd.sqlite3",
                )
            },
        )
        assert incompatible_response.status_code == 400
        assert "缺少 ProjMemo 必要資料表" in incompatible_response.text
        assert "還原後應消失的專案" in client.get("/").text

        restore_response = client.post(
            "/settings/backup/restore",
            files={
                "backup_file": (
                    "projmemo-test.sqlite3",
                    backup_response.content,
                    "application/vnd.sqlite3",
                )
            },
        )
        assert restore_response.status_code == 303
        restored_page = client.get(restore_response.headers["location"])
        assert restored_page.status_code == 200
        assert "資料還原完成" in restored_page.text
        assert "還原前自動備份" in restored_page.text
        restored_projects = client.get("/").text
        assert "測試專案" in restored_projects
        assert "還原後應消失的專案" not in restored_projects

        recovery_link = next(
            line.split('href="', 1)[1].split('"', 1)[0]
            for line in restored_page.text.splitlines()
            if "下載還原前自動備份" in line
        )
        recovery_response = client.get(recovery_link)
        assert recovery_response.status_code == 200
        assert recovery_response.content.startswith(b"SQLite format 3\x00")
        recovery_path = tmp_path / "projmemo-recovery.sqlite3"
        recovery_path.write_bytes(recovery_response.content)
        with sqlite3.connect(recovery_path) as recovery_connection:
            restored_backup_name = recovery_connection.execute(
                "SELECT name FROM projects WHERE name = ?", ("還原後應消失的專案",)
            ).fetchone()
            assert restored_backup_name == ("還原後應消失的專案",)
