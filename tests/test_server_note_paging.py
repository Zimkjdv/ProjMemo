from contextlib import closing
import re
import sqlite3

import pytest

from app.main import create_app
from app.services.projects import load_project_data
from app.services.workspace import load_workspace
from tests.client import TestClient


@pytest.fixture
def paged(tmp_path, monkeypatch):
    path = tmp_path / "paged.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    with TestClient(create_app()) as client:
        client.post("/projects/new", data={"name": "Paging fixture"})
        with closing(sqlite3.connect(path)) as c, c:
            c.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,?)",
                [(f'Fixture {i:04}', f'Body {i:04}\n\n```python\nprint({i})\n```') for i in range(1,1001)])
        yield client, path


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("size,page,first,last", [(10,1,1000,991),(20,2,980,961),(50,20,50,1),(20,999,20,1),(50,-1,1000,951)])
def test_true_sql_paging_independent_counts_and_native_fallback(paged, language, size, page, first, last):
    client, _ = paged
    client.cookies.set("projmemo_language", language)
    response = client.get(f"/projects/1?notes_size={size}&notes_page={page}")
    assert response.status_code == 200
    assert response.text.count('class="note-card ') == size
    assert f'Fixture {first:04}' in response.text and f'Fixture {last:04}' in response.text
    assert 'data-note-total="1000"' in response.text
    assert 'class="jump-count">1000<' in response.text and 'class="section-count">1000<' in response.text
    assert 'method="get"' in response.text and 'data-note-page href="/projects/1?' in response.text
    assert ('Notes per page' if language == 'en' else '每頁備註數量') in response.text
    assert "value=\"0\"" not in response.text


def test_fragment_reads_only_notes_and_never_export_secrets(paged, monkeypatch):
    client, _ = paged
    monkeypatch.setattr("app.services.workspace.project_related", lambda *_: pytest.fail("Fragment must not load other sections"))
    response = client.get("/projects/1?notes_page=50&notes_size=20", headers={"X-ProjMemo-Fragment":"notes"})
    assert response.status_code == 200 and response.headers["X-ProjMemo-Fragment"] == "notes"
    assert 'Vary' in response.headers and 'no-store' in response.headers['cache-control']
    assert response.text.count('class="note-card ') == 20
    assert 'Fixture 0001' in response.text and '<header' not in response.text and '<script' not in response.text


@pytest.mark.parametrize("page,size", [("garbage","garbage"),("9"*100,"0"),("0","5000")])
def test_bad_page_parameters_are_bounded(paged, page, size):
    values = load_workspace(1, page=page, size=size)
    assert values['note_page']['size'] == 20 and values['note_page']['number'] == 1
    assert len(values['notes']) == 20


def test_full_projection_markdown_pdf_and_backup_are_not_ui_limited(paged, monkeypatch):
    client, _ = paged
    assert len(load_project_data(1).notes) == 1000
    exported = client.get('/projects/1/export.md?notes_page=50&notes_size=10').text
    assert all(f'Fixture {i:04}' in exported for i in range(1,1001))
    def pdf(_project,_urls,notes,*_args,**_kwargs):
        assert len(notes) == 1000
        return b'%PDF-fixture'
    monkeypatch.setattr('app.services.exports.generate_project_pdf',pdf)
    assert client.get('/projects/1/export.pdf?notes_size=10').content.startswith(b'%PDF-')
    backup = client.get('/settings/backup/download')
    assert backup.content.startswith(b'SQLite format 3\x00')


def test_error_on_deep_note_reopens_correct_page_and_preserves_draft(paged):
    client, _ = paged
    token = re.search(r'name="_submission_token" value="([^"]+)"',client.get('/projects/1').text)[1]
    response=client.post('/notes/1/edit',data={'title':' ', 'content_markdown':'Deep draft', '_submission_token':token, '_notes_size':'10'}, headers={'Accept':'text/html'})
    assert response.status_code == 400
    assert 'Deep draft' in response.text and 'data-notes-page="100"' in response.text
    assert 'data-recovery-url="/projects/1?notes_page=100&amp;notes_size=10' in response.text
    assert 'class="item-actions" open' in response.text


def test_empty_and_deletion_clamp_pages_without_cross_project_content(paged):
    client, path = paged
    client.post('/projects/new',data={'name':'Empty fixture'})
    values=load_workspace(2,page='999')
    assert values['note_total'] == 0 and values['notes'] == [] and values['note_page']['number'] == 1
    with closing(sqlite3.connect(path)) as c,c:
        c.execute('DELETE FROM notes WHERE id <= 20')
    values=load_workspace(1,page='50')
    assert values['note_page']['number'] == 49 and len(values['notes']) == 20
