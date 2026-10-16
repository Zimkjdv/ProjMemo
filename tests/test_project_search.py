"""R10 read-only search, exact filters, progress and pending-view continuity."""

import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from app import db
from app.errors import ApplicationError
from app.form_errors import FormDocument
from app.main import create_app
from app.project_search import CONTENT_FIELDS, has_token
from app.runtime import AppRuntime
from app.services import accounts, projects, vault
from app.services.workspace import load_workspace
from tests.client import TestClient


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "search.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    db.init_db(path)
    with db.db_session(write=True) as connection:
        connection.executemany("INSERT INTO projects(id,name,status,owner,tags) VALUES(?,?,?,?,?)", [
            (1, "Primary 專案", "handover", "Ryan, Mei", "Python, C++"),
            (2, "Similar 專案", "handover", "Ryan2", "Pythonista"),
            (3, "Complete 專案", "completed", "Mei", "Web"),
        ])
        connection.execute("INSERT INTO project_urls(project_id,title,url) VALUES(1,'Fixture link','https://example.invalid/')")
        connection.execute("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,'Fixture note','Retained body')")
        connection.execute("INSERT INTO checklist_items(project_id,title,completed) VALUES(1,'Pending transfer',0)")
        connection.execute("INSERT INTO checklist_items(project_id,title,completed) VALUES(1,'Completed transfer',1)")
        connection.execute("INSERT INTO checklist_items(project_id,title,completed) VALUES(3,'Done transfer',1)")
        connection.execute("INSERT INTO environment_variables(project_id,key) VALUES(1,'FIXTURE_CONFIG')")
        connection.execute("INSERT INTO access_accounts(project_id,label) VALUES(1,'Fixture account')")
    return path


def ids(**values):
    return [row["id"] for row in projects.list_projects(**values)["projects"]]


@pytest.mark.parametrize("table,field", [(table, field) for table, fields in CONTENT_FIELDS.items() for field in fields])
def test_each_allowed_content_field_is_opt_in_and_supports_chinese_substrings(database, table, field):
    with db.db_session(write=True) as connection:
        connection.execute(f"UPDATE {table} SET {field} = ? WHERE project_id=1", ("Prefix 部署搜尋 Suffix",))
    assert ids(q="部署搜尋") == []
    assert ids(q="部署搜尋", search_scope="all") == [1]


@pytest.mark.parametrize("field", ["name", "description", "owner", "tags"])
def test_basic_search_includes_owner_without_loading_child_text(database, field):
    with db.db_session(write=True) as connection:
        connection.execute(f"UPDATE projects SET {field}=? WHERE id=1", ("Basic marker-find",))
    assert ids(q="MARKER-find") == [1]


@pytest.mark.parametrize("value", ["50%_done\\path", "O'Reilly", "'; DROP TABLE projects; --", "<script>fixture</script>"])
def test_search_is_literal_parameterized_and_not_a_sql_wildcard(database, value):
    with db.db_session(write=True) as connection:
        connection.execute("UPDATE projects SET description=? WHERE id=1", (value,))
    assert ids(q=value) == [1]
    assert projects.list_projects()["total_count"] == 3


def test_exact_unicode_tokens_do_not_match_substrings_and_read_legacy_separators(database):
    assert ids(owner="ryan") == [1]
    assert ids(tag="PYTHON") == [1]
    assert ids(tag="Pythonista") == [2]
    assert ids(owner="Ryan", tag="C++", status="handover", handover="pending") == [1]
    assert ids(owner="Mei", tag="Pythonista") == []
    assert has_token(" Alice；Straße、工程團隊\nALICE", "STRASSE") == 1
    assert has_token("Pythonista, API", "Python") == 0
    before = database.read_bytes()
    assert ids(owner=" Ryan ") == [1]
    assert database.read_bytes() == before


@pytest.mark.parametrize("handover,expected", [("pending", [1]), ("complete", [3]), ("none", [2]), ("invalid", [3, 2, 1])])
def test_progress_filters_distinguish_empty_from_complete(database, handover, expected):
    values = projects.list_projects(handover=handover)
    assert [row["id"] for row in values["projects"]] == expected
    progress = projects.list_projects()["handover_progress"]
    assert progress[1] == {"total": 2, "completed": 1, "pending": 1, "percent": 50}
    assert progress[2] == {"total": 0, "completed": 0, "pending": 0, "percent": None}
    assert progress[3]["percent"] == 100


def test_many_matching_children_do_not_duplicate_projects_or_progress(database):
    with db.db_session(write=True) as connection:
        connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,'Repeat needle','needle')", [()] * 30)
    values = projects.list_projects(q="needle", search_scope="all")
    assert values["total_count"] == 1 and len(values["projects"]) == 1
    assert values["handover_progress"][1]["total"] == 2


def test_search_never_reads_secret_columns_or_derives_keys(database, monkeypatch):
    runtime = AppRuntime()
    key = vault.setup(runtime, "test-only-r10-master", "test-only-r10-master")
    token = vault.issue_session(runtime, key, None)
    accounts.add_access_account(runtime=runtime, token=token, project_id=1, label="Encrypted fixture", secret_value="test-only-r10-hidden-secret")
    original = db.connect
    reads = []
    def guarded(path):
        connection = original(path)
        def authorize(action, table, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ:
                reads.append((table, column))
                if table == "vault_config" or column in {"secret_ciphertext", "secret_nonce", "secret_value"}:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connection.set_authorizer(authorize)
        return connection
    monkeypatch.setattr(db, "connect", guarded)
    monkeypatch.setattr(accounts, "decrypt_secret", lambda *_: pytest.fail("Search must not decrypt"))
    assert ids(q="test-only-r10-hidden-secret", search_scope="all") == []
    assert ids(q="test-only-r10-master", search_scope="all") == []
    assert ids(q="Encrypted fixture", search_scope="all") == [1]
    assert ("access_accounts", "label") in reads


def test_content_lookup_uses_existing_project_scoped_indexes_and_never_creates_search_schema(database):
    from app.project_search import normalized_filters, project_where
    before = database.read_bytes()
    where, params = project_where(collection="active", status="", **normalized_filters(q="部署", search_scope="all"))
    with db.db_session() as connection:
        plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN SELECT COUNT(*) FROM projects" + where, params))
        assert "SEARCH projects USING INDEX idx_projects_lifecycle" in plan
        for name in ("idx_urls_project_order", "idx_notes_project_order", "idx_checklist_project_order", "idx_environment_project_order", "idx_accounts_project_order"):
            assert name in plan
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT name FROM sqlite_master WHERE sql LIKE '%VIRTUAL TABLE%'").fetchall() == []
    assert database.read_bytes() == before


@pytest.mark.parametrize("collection", ["active", "archived", "trash"])
def test_collection_boundaries_and_trash_cannot_probe_hidden_content(database, collection):
    with db.db_session(write=True) as connection:
        if collection != "active":
            column = "archived_at" if collection == "archived" else "deleted_at"
            connection.execute(f"UPDATE projects SET {column}=CURRENT_TIMESTAMP WHERE id=1")
    values = projects.list_projects(collection=collection, q="Retained body", search_scope="all")
    assert values["total_count"] == (0 if collection == "trash" else 1)
    assert values["search_scope"] == ("basic" if collection == "trash" else "all")
    assert ids(collection=collection, owner="Ryan", tag="Python") == [1]
    options = projects.list_projects(collection=collection)
    assert "Ryan" in options["owner_options"]
    assert ("Ryan2" in options["owner_options"]) == (collection == "active")


@pytest.mark.parametrize("size", [10, 20, 50])
def test_filtered_paging_urls_keep_every_applied_condition(database, size):
    with db.db_session(write=True) as connection:
        for number in range(23):
            cursor = connection.execute("INSERT INTO projects(name,status,owner,tags,archived_at) VALUES(?, 'handover','Ryan','C++',CURRENT_TIMESTAMP)", (f"Page {number:02}",))
            connection.execute("INSERT INTO checklist_items(project_id,title) VALUES(?,'deploy needle')", (cursor.lastrowid,))
    values = projects.list_projects(collection="archived", q="needle", search_scope="all", owner="Ryan", tag="C++", handover="pending", status="handover", page_size=size, page=999, view="list")
    assert values["total_count"] == 23 and len(values["projects"]) == (23 % size or size)
    assert values["page"] == (23 + size - 1) // size
    for field in ("card_view_url", "list_view_url", "previous_url"):
        if not values[field]:
            continue
        query = parse_qs(urlsplit(values[field]).query)
        for name, expected in {"collection": "archived", "q": "needle", "search_scope": "all", "owner": "Ryan", "tag": "C++", "handover": "pending", "status": "handover"}.items():
            assert query[name] == [expected]
    cleared = parse_qs(urlsplit(values["clear_filter_url"]).query)
    assert set(cleared) == {"view", "page_size", "page", "collection"}
    assert values["list_preferences"]["tag"] == "C++"


def test_datalist_is_bounded_and_manually_typed_values_still_work(database):
    with db.db_session(write=True) as connection:
        connection.executemany("INSERT INTO projects(name,owner,tags) VALUES(?,?,?)",
            [(f"Option {number}", f"Owner {number}", f"Tag {number}") for number in range(205)])
    values = projects.list_projects()
    assert len(values["owner_options"]) == len(values["tag_options"]) == 200
    assert len(ids(owner="Owner 204", tag="Tag 204")) == 1


def test_owner_and_tag_named_basic_are_not_confused_with_default_search_scope(database):
    values = projects.list_projects(owner="basic", tag="basic")
    assert values["list_preferences"]["owner"] == values["list_preferences"]["tag"] == "basic"
    assert "search_scope" not in values["list_preferences"]


@pytest.mark.parametrize("values", [{"q": "x" * 257}, {"owner": "x" * 1001}, {"tag": "x" * 1001}, {"q": "a\x00b"}])
def test_overlong_or_null_search_input_is_rejected_without_writes(database, values):
    before = database.read_bytes()
    with pytest.raises(ApplicationError) as error:
        projects.list_projects(**values)
    assert error.value.status_code == 400 and database.read_bytes() == before


def hidden_fields(markup, action):
    form = next(node for node in FormDocument(markup).root.walk() if node.tag == "form" and node.attrs.get("action") == action)
    return {node.attrs["name"]: node.attrs.get("value", "") for node in form.walk()
            if node.tag == "input" and node.attrs.get("type") == "hidden"}


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_native_pending_actions_error_recovery_notes_and_complete_exports(database, language):
    with db.db_session(write=True) as connection:
        connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,'Body')", [(f"Page note {n}",) for n in range(25)])
    with TestClient(create_app(), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        address = "/projects/1?checklist=pending&notes_size=10&notes_page=2&detail_view=list"
        response = client.get(address)
        assert response.status_code == 200
        assert response.text.count('class="checklist-item ') == 1
        assert "Completed transfer" not in response.text
        assert "Pending transfer" in response.text
        assert 'aria-label="1 of 2 items completed"' in response.text if language == "en" else 'aria-label="已完成 1 項，共 2 項"' in response.text
        assert response.text.count('class="jump-count">2</span>') == 1
        assert 'name="checklist" value="pending"' in response.text
        fragment = client.get(address, headers={"X-ProjMemo-Fragment": "notes"})
        assert 'name="_checklist_filter" value="pending"' in fragment.text
        action = "/checklist/1/edit"
        form = hidden_fields(response.text, action)
        failed = client.post(action, data=form | {"title": "x" * 201, "category": "other"}, headers={"Accept": "text/html"})
        assert failed.status_code == 400 and "checklist=pending" in failed.text
        assert 'data-recovered-form="true"' in failed.text
        action = "/checklist/1/toggle"
        form = hidden_fields(response.text, action)
        toggled = client.post(action, data=form, headers={"Accept": "text/html"})
        assert toggled.status_code == 303
        query = parse_qs(urlsplit(toggled.headers["location"]).query)
        assert query["checklist"] == ["pending"] and query["notes_page"] == ["2"] and query["detail_view"] == ["list"]
        replay = client.post(action, data=form, headers={"Accept": "text/html"})
        assert replay.headers["location"] == toggled.headers["location"]
        empty = client.get(toggled.headers["location"])
        assert empty.text.count('class="checklist-item ') == 0
        assert "No unfinished handover items" in empty.text if language == "en" else "沒有未完成的交接項目" in empty.text
        exported = client.get("/projects/1/export.md?checklist=pending")
        assert "Pending transfer" in exported.text and "Completed transfer" in exported.text
        assert projects.list_projects()["handover_progress"][1]["percent"] == 100


def test_workspace_keeps_full_checklist_for_counts_and_export_projection(database):
    values = load_workspace(1, checklist_filter="pending")
    assert len(values["checklist"]) == 2 and len(values["visible_checklist"]) == 1
    assert values["checklist_progress"]["total"] == 2
    assert "checklist=pending" in values["note_page"]["start"]
    assert len(projects.load_project_data(1).checklist) == 2


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_search_page_is_escaped_bilingual_and_new_filter_empty_states_are_real(database, language):
    with TestClient(create_app()) as client:
        client.cookies.set("projmemo_language", language)
        response = client.get("/", params={"q": "Retained body", "owner": "Ryan", "tag": "Python", "handover": "pending", "search_scope": "all", "view": "list"})
        assert response.status_code == 200 and response.text.count('class="project-list-row"') == 1
        assert "Advanced filters" in response.text if language == "en" else "進階篩選" in response.text
        assert 'href="/projects/1?checklist=pending#handover"' in response.text
        empty = client.get("/", params={"owner": '<script>fixture</script>'})
        assert '<script>fixture</script>' not in empty.text
        assert "No matching projects" in empty.text if language == "en" else "沒有符合條件的專案" in empty.text
        assert 'name="owner" value="&lt;script&gt;fixture&lt;/script&gt;"' in empty.text
        # Applied preferences are escaped JSON and contain no content rows.
        document = FormDocument(response.text)
        state = next(node for node in document.root.walk() if node.attrs.get("id") == "list-preferences")
        assert json.loads("".join(state.children))["search_scope"] == "all"
