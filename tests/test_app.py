from pathlib import Path

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
