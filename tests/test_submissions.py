import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import ApplicationError
from app.main import create_app
from app.submissions import SubmissionRegistry
from tests.client import TestClient


def test_registry_only_one_concurrent_claim_and_same_response_replay():
    registry = SubmissionRegistry()
    token = registry.issue("browser")
    def claim():
        try:
            return registry.claim(token, "browser", "/projects/1/notes")
        except ApplicationError as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(), range(8)))
    assert results.count(None) == 1 and results.count(409) == 7
    registry.finish(token, "/projects/1?notice=saved#project-notes")
    assert claim() == "/projects/1?notice=saved#project-notes"
    with pytest.raises(ApplicationError):
        registry.claim(token, "browser", "/projects/2/notes")


def test_tokens_bound_to_browser_ttl_runtime_and_capacity_without_eviction():
    now = [100]
    registry = SubmissionRegistry(clock=lambda: now[0], capacity=1)
    token = registry.issue("a")
    for value, browser in [(token, "b"), (token + "x", "a"), ("bad", "a"), (None, "a")]:
        with pytest.raises(ApplicationError):
            registry.claim(value, browser, "/notes")
    assert registry.claim(token, "a", "/notes") is None
    with pytest.raises(ApplicationError) as caught:
        registry.claim(registry.issue("a"), "a", "/notes")
    assert caught.value.status_code == 503
    registry.finish(token, "/done")
    assert registry.claim(token, "a", "/notes") == "/done"
    now[0] += 86400
    with pytest.raises(ApplicationError):
        registry.claim(token, "a", "/notes")
    assert registry.claim(registry.issue("a"), "a", "/notes") is None
    with pytest.raises(ApplicationError):
        SubmissionRegistry().claim(token, "a", "/notes")


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_browser_retries_do_not_duplicate_notes_or_toggle_twice(tmp_path, monkeypatch, language):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "submissions.db"))
    with TestClient(create_app(), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        client.get("/")
        client.post("/projects/new", data={"name": "Fixture"})
        client.post("/projects/1/checklist", data={"title": "Transfer"})
        for path, data, section in [("/projects/1/notes", {"title": "Only once", "content_markdown": "body"}, "project-notes"),
                                    ("/checklist/1/toggle", {}, "handover")]:
            token = re.search(r'name="_submission_token" value="([^"]+)"', client.get("/projects/1").text)[1]
            data = {**data, "_submission_token": token, "_detail_view": "list"}
            first = client.post(path, data=data, headers={"Accept": "text/html"})
            second = client.post(path, data=data, headers={"Accept": "text/html"})
            assert first.status_code == second.status_code == 303
            assert first.headers["location"] == second.headers["location"]
            assert first.headers["location"].endswith("#" + section)
            page = client.get(first.headers["location"])
            assert "Changes saved." in page.text if language == "en" else "已儲存變更。" in page.text
        from app.services.projects import load_project_data
        projection = load_project_data(1)
        assert len(projection.notes) == 1 and projection.checklist[0]["completed"] == 1


def test_validation_retry_reuses_token_and_security_precedes_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "retry.db"))
    with TestClient(create_app(), follow_redirects=False) as client:
        page = client.get("/projects/new")
        token = re.search(r'name="_submission_token" value="([^"]+)"', page.text)[1]
        failed = client.post("/projects/new", data={"name": " ", "_submission_token": token}, headers={"Accept": "text/html"})
        assert failed.status_code == 400 and token in failed.text
        for _ in range(2):
            saved = client.post("/projects/new", data={"name": "Only once", "_submission_token": token}, headers={"Accept": "text/html"})
            assert saved.status_code == 303
        assert "Only once" in client.get("/projects/1").text
        assert client.get("/projects/2").status_code == 404
