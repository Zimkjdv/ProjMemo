"""Synthetic R10 measurements and FTS semantics; never use the configured DB.

Run: .venv/Scripts/python.exe -X utf8 scripts/benchmark_r10.py
Only TemporaryDirectory databases are used. No DB-path argument is accepted.
"""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import db_session, init_db
from app.main import create_app
from app.project_search import has_token, normalized_filters, project_where
from app.services.projects import list_projects
from tests.client import TestClient


def seed(path, count):
    init_db(path)
    with db_session(path, write=True) as connection:
        connection.executemany("INSERT INTO projects(id,name,owner,tags) VALUES(?,?,?,?)", [
            (number, f"Bench project {number:04}", f"Team {number % 20}", "Python, Demo" if number % 2 == 0 else "Web, Demo")
            for number in range(1, count + 1)])
        connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(?,?,?)", [
            (number, f"Note {item}", "部署前檢查備份。 " * 12 +
             ("release-marker" if number % 25 == 0 and item == 19 else "ordinary fixture"))
            for number in range(1, count + 1) for item in range(20)])
        for number in range(1, count + 1):
            for item in range(2):
                connection.execute("INSERT INTO project_urls(project_id,title,url) VALUES(?,'Docs','https://example.invalid')", (number,))
                connection.execute("INSERT INTO checklist_items(project_id,title,completed) VALUES(?,'Transfer',?)", (number, item))
                connection.execute("INSERT INTO environment_variables(project_id,key,description) VALUES(?,'FIXTURE','Fixture configuration')", (number,))
                connection.execute("INSERT INTO access_accounts(project_id,label,username) VALUES(?,'Fixture account','fixture-user')", (number,))


def fts_semantics():
    results = {}
    with closing(sqlite3.connect(":memory:")) as connection:
        for tokenizer in ("unicode61", "trigram"):
            try:
                connection.execute(f"CREATE VIRTUAL TABLE prototype_{tokenizer} USING fts5(body, tokenize='{tokenizer}')")
                connection.execute(f"INSERT INTO prototype_{tokenizer}(body) VALUES('部署前先備份 release-marker')")
                comparisons = []
                for query in ("署", "部署", "部署前", "lease", "release"):
                    count = connection.execute(f"SELECT COUNT(*) FROM prototype_{tokenizer} WHERE prototype_{tokenizer} MATCH ?", ('"' + query + '"',)).fetchone()[0]
                    literal = connection.execute(f"SELECT COUNT(*) FROM prototype_{tokenizer} WHERE instr(body, ?) > 0", (query,)).fetchone()[0]
                    comparisons.append({"query": query, "fts_matches": count, "literal_substring_matches": literal})
                results[tokenizer] = {"available": True, "comparisons": comparisons}
            except sqlite3.OperationalError:
                results[tokenizer] = {"available": False}
    return results


def main():
    previous = os.environ.get("PROJMEMO_DB_PATH")
    print(json.dumps({"environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                                      "platform": platform.system()}}, ensure_ascii=True), flush=True)
    try:
        with TemporaryDirectory(prefix="projmemo-r10-") as directory:
            for count in (250, 1000):
                path = Path(directory) / f"fixture-{count}.db"
                os.environ["PROJMEMO_DB_PATH"] = str(path)
                seed(path, count)
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with TestClient(create_app()) as client:
                    cases = {"basic": {"q": "Bench"},
                             "content_rare": {"q": "release-marker", "search_scope": "all"},
                             "content_missing": {"q": "missing-marker", "search_scope": "all"},
                             "content_cjk": {"q": "部署", "search_scope": "all"},
                             "combined": {"q": "release-marker", "search_scope": "all", "owner": "Team 0", "tag": "Python", "handover": "pending"}}
                    for name, filters in cases.items():
                        service_times, html_times = [], []
                        for attempt in range(6):
                            start = perf_counter()
                            result = list_projects(**filters, page_size=10)
                            service_ms = (perf_counter() - start) * 1000
                            start = perf_counter()
                            response = client.get("/", params=filters | {"page_size": 10})
                            html_ms = (perf_counter() - start) * 1000
                            assert response.status_code == 200
                            if attempt:
                                service_times.append(service_ms)
                                html_times.append(html_ms)
                        selected = normalized_filters(**filters)
                        where, params = project_where(collection="active", status="", **selected)
                        with db_session() as connection:
                            connection.create_function("projmemo_has_token", 2, has_token, deterministic=True)
                            plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN SELECT COUNT(*) FROM projects" + where, params)]
                        print(json.dumps({"projects": count, "notes": count * 20, "case": name,
                            "matches": result["total_count"], "rows": len(result["projects"]),
                            "service_median_ms": round(median(service_times), 2),
                            "html_median_ms": round(median(html_times), 2), "html_bytes": len(response.content),
                            "plan": plan}, ensure_ascii=True), flush=True)
                assert hashlib.sha256(path.read_bytes()).hexdigest() == before, "Search must not rewrite its fixture DB"
            print(json.dumps({"fts_semantics": fts_semantics()}, ensure_ascii=True), flush=True)
    finally:
        if previous is None:
            os.environ.pop("PROJMEMO_DB_PATH", None)
        else:
            os.environ["PROJMEMO_DB_PATH"] = previous


if __name__ == "__main__":
    main()
