"""Final R05 acceptance, isolated from the user's local database."""

from contextlib import closing
import re
import sqlite3

import pytest

from app.main import create_app
from app.runtime import AppRuntime
from app.services.projects import load_project_data
from app.vault import VaultSessions
from tests.client import TestClient


def token_for(client, path="/projects/new"):
    return re.search(r'name="_submission_token" value="([^"]+)"', client.get(path).text)[1]


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("path,data,expected", [
    ("/projects/new", {"description":"Recover me"}, 422),
    ("/projects/new", {"name":"", "description":"Recover me"}, 400),
    ("/projects/new", {"name":"x"*201, "description":"Recover me"}, 400),
    ("/projects/1/urls", {"title":"Recover me", "url":"https://"}, 400),
    ("/projects/1/urls", {"title":"Recover me", "url":"https://example.invalid:99999"}, 400),
    ("/projects/1/urls", {"title":"Recover me", "url":"https://example.invalid", "type":"unknown"}, 400),
    ("/projects/1/notes", {"title":"Recover me", "content_markdown":"x"*100001}, 400),
    ("/projects/1/accounts", {"label":" ", "username":"Recover me", "secret_value":"Do-not-echo-fixture"}, 400),
])
def test_recoverable_localized_field_errors(tmp_path, monkeypatch, language, path, data, expected):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path/"accept.db"))
    with TestClient(create_app(),follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        client.get("/")
        client.post("/projects/new",data={"name":"Fixture"})
        response=client.post(path,data={**data,"_submission_token":token_for(client)},headers={"Accept":"text/html"})
        assert response.status_code == expected
        assert "Recover me" in response.text and "Do-not-echo-fixture" not in response.text
        assert ('Check your input' if language=='en' else '請檢查輸入資料') in response.text
        assert 'aria-invalid="true"' in response.text
        projection=load_project_data(1)
        assert projection.urls == [] and projection.notes == [] and projection.access_accounts == []
        assert client.get('/projects/2').status_code == 404


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_expired_vault_unlock_then_reenter_secret_and_retry_exactly_once(tmp_path, monkeypatch, language):
    path=tmp_path/'expiry.db'
    monkeypatch.setenv('PROJMEMO_DB_PATH',str(path))
    now=[0.0]
    runtime=AppRuntime(vault_sessions=VaultSessions(ttl_seconds=1,clock=lambda:now[0]))
    with TestClient(create_app(runtime),follow_redirects=False) as client:
        client.cookies.set('projmemo_language',language)
        client.get('/')
        client.post('/projects/new',data={'name':'Expiry fixture'})
        master='R05 isolated master phrase'
        assert client.post('/settings/vault/setup',data={'master_password':master,'confirm_password':master}).status_code==303
        token=token_for(client,'/projects/1')
        values={'label':'Retained account draft','username':'fixture-user','owner':'Team',
                'secret_value':'Exact fixture password  ','_submission_token':token}
        now[0]=2.0
        failed=client.post('/projects/1/accounts',data=values,headers={'Accept':'text/html'})
        assert failed.status_code==423
        assert 'Retained account draft' in failed.text and 'fixture-user' in failed.text
        assert values['secret_value'] not in failed.text and master not in failed.text
        assert load_project_data(1).access_accounts==[]
        assert client.post('/settings/vault/unlock',data={'master_password':master}).status_code==303
        for _ in range(2):
            saved=client.post('/projects/1/accounts',data=values,headers={'Accept':'text/html'})
            assert saved.status_code==303 and saved.headers['location'].endswith('#access-accounts')
        assert len(load_project_data(1).access_accounts)==1
        assert client.post('/accounts/1/reveal').json()['secret']==values['secret_value']
        assert values['secret_value'] not in client.get('/projects/1/export.md').text
        with closing(sqlite3.connect(path)) as connection:
            encrypted=connection.execute('SELECT secret_ciphertext FROM access_accounts').fetchone()[0]
            assert isinstance(encrypted,bytes) and values['secret_value'].encode() not in encrypted


def test_native_deep_edit_keeps_page_without_javascript_and_replay_has_no_duplicate(tmp_path, monkeypatch):
    # Hidden page state is delivered in HTML; JS is not needed to construct it.
    monkeypatch.setenv('PROJMEMO_DB_PATH',str(tmp_path/'native.db'))
    from app.form_errors import FormDocument
    with TestClient(create_app(),follow_redirects=False) as client:
        client.post('/projects/new',data={'name':'Native fixture'})
        from app.db import db_session
        with db_session(write=True) as connection:
            connection.executemany('INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,?)',[(str(i),'body') for i in range(100)])
        page=client.get('/projects/1?notes_page=5&notes_size=20&detail_view=list')
        form=next(node for node in FormDocument(page.text).root.walk() if node.tag=='form' and node.attrs.get('action')=='/notes/1/edit')
        values={node.attrs['name']:node.attrs.get('value','') for node in form.walk() if node.tag=='input' and node.attrs.get('type')=='hidden'}
        values.update(title='Native saved',content_markdown='body')
        first=client.post('/notes/1/edit',data=values,headers={'Accept':'text/html'})
        second=client.post('/notes/1/edit',data=values,headers={'Accept':'text/html'})
        assert first.status_code==second.status_code==303
        assert first.headers['location']==second.headers['location']
        assert 'notes_page=5' in first.headers['location'] and 'notes_size=20' in first.headers['location'] and 'detail_view=list' in first.headers['location']
        assert len(load_project_data(1).notes)==100


def test_json_validation_preserves_documented_shape_without_input_or_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv('PROJMEMO_DB_PATH',str(tmp_path/'json.db'))
    with TestClient(create_app()) as client:
        response=client.post('/settings/vault/setup',data={'master_password':'Never-echo-fixture'})
        assert response.status_code==422
        assert isinstance(response.json()['detail'],list)
        assert all(set(item)=={'loc','msg','type'} for item in response.json()['detail'])
        assert 'Never-echo-fixture' not in response.text


def test_malformed_non_ascii_token_is_rejected_not_internal_error():
    from app.errors import ApplicationError
    from app.submissions import SubmissionRegistry
    with pytest.raises(ApplicationError):
        SubmissionRegistry(clock=lambda:1).claim('1.nonce.非英文','browser','/projects/new')
