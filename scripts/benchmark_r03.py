"""Reproducible synthetic R03 measurements; never open the configured user DB.

Run with .venv/Scripts/python.exe -X utf8 scripts/benchmark_r03.py.
All databases live in a TemporaryDirectory and are removed on exit.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
from statistics import median
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.migrations import QUERY_INDEXES, baseline_schema, migration_history
from app.db import init_db
from app.services.projects import project_detail
from app.sqlite_policy import copy_database


NOTE = "## Fixture deployment\n\n" + ("部署前檢查環境與備份。 Review the environment and recovery procedure.\n" * 6)


def emit(kind, value):
    print(json.dumps({"kind": kind, **value}, ensure_ascii=False), flush=True)


def seed(connection, projects, rows, target):
    connection.executemany(
        "INSERT INTO projects(id,name,status,updated_at) VALUES (?,?,?,?)",
        [(number, f"Fixture project {number:04}", ("maintenance", "handover", "completed")[number % 3],
          f"2026-10-{number % 28 + 1:02} 12:00:00") for number in range(1, projects + 1)],
    )
    pairs = [(project_id, number) for project_id in range(1, projects + 1) for number in range(rows)]
    connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES (?,?,?)",
                           [(pid, f"Note {number:03}", NOTE) for pid in range(1, projects + 1)
                            for number in range(250 if pid == target else rows)])
    connection.executemany("INSERT INTO project_urls(project_id,title,url) VALUES (?,?,?)",
                           [(pid, f"URL {number:03}", f"https://example.invalid/{pid}/{number}") for pid, number in pairs])
    connection.executemany("INSERT INTO checklist_items(project_id,title,completed) VALUES (?,?,?)",
                           [(pid, f"Transfer {number:03}", number % 2) for pid, number in pairs])
    environments = ("local", "staging", "production", "development")
    connection.executemany("INSERT INTO environment_variables(project_id,key,environment) VALUES (?,?,?)",
                           [(pid, f"FIXTURE_{number:03}", environments[number % 4]) for pid, number in pairs])
    connection.executemany("INSERT INTO access_accounts(project_id,label,environment,username,endpoint) VALUES (?,?,?,?,?)",
                           [(pid, f"Account {number:03}", environments[number % 4], "fixture-user", "host.example.invalid") for pid, number in pairs])
    connection.commit()


def queries(connection, target):
    statements = []
    connection.set_trace_callback(statements.append)
    project_detail(connection, target)
    connection.set_trace_callback(None)
    names = ("project", "urls", "checklist", "environment", "accounts", "notes")
    result = {name: (statement, ()) for name, statement in zip(names, statements)}
    # Compare the same released business projection across schemas. SELECT *
    # would add v4 lifecycle columns to only one side of the v2/v3 comparison.
    project_columns = "id,name,description,status,owner,tags,created_at,updated_at"
    result.update({
        "home": (f"SELECT {project_columns} FROM projects ORDER BY updated_at DESC, id DESC LIMIT 20 OFFSET 0", ()),
        "home_status": (f"SELECT {project_columns} FROM projects WHERE status=? ORDER BY updated_at DESC, id DESC LIMIT 20 OFFSET 0", ("maintenance",)),
        "home_search": (f"SELECT {project_columns} FROM projects WHERE name LIKE ? OR description LIKE ? OR tags LIKE ? ORDER BY updated_at DESC, id DESC LIMIT 20", ("%project%",) * 3),
        "notes_page_prototype": ("SELECT * FROM notes WHERE project_id=? ORDER BY id DESC LIMIT 20 OFFSET 0", (target,)),
        "accounts_sensitive_sort": ("SELECT id,label,username,secret_ciphertext,secret_nonce FROM access_accounts WHERE project_id=? ORDER BY label COLLATE NOCASE", (target,)),
    })
    return result


def measure(connection, cases, repetitions):
    results = {}
    for name, (statement, parameters) in cases.items():
        plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + statement, parameters)]
        durations = []
        for _ in range(repetitions + 1):
            started = perf_counter()
            rows = connection.execute(statement, parameters).fetchall()
            durations.append((perf_counter() - started) * 1000)
        digest = hashlib.sha256(json.dumps([tuple(row) for row in rows], ensure_ascii=False).encode()).hexdigest()
        ticks = [0]
        def progress():
            ticks[0] += 1
            return 0
        connection.set_progress_handler(progress, 100)
        connection.execute(statement, parameters).fetchall()
        connection.set_progress_handler(None, 0)
        results[name] = {"median_ms": round(median(durations[1:]), 4), "rows": len(rows),
                         "approx_vm_steps": ticks[0] * 100, "digest": digest, "plan": plan}
    return results


def writer_wait(path, release_after):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    released = Event()
    writer = sqlite3.connect(path)
    writer.execute("BEGIN IMMEDIATE")
    def competing_write():
        started = perf_counter()
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute("UPDATE projects SET description='fixture lock probe' WHERE id=1")
            connection.commit()
        return round((perf_counter() - started) * 1000, 2)
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(competing_write)
        released.wait(release_after)
        writer.rollback()
        writer.close()
        return pending.result(timeout=6)


def upgrade_cost(path, directory):
    target = directory / "upgrade" / "database.db"
    target.parent.mkdir()
    copy_database(path, target)
    start = perf_counter()
    init_db(target)
    elapsed = (perf_counter() - start) * 1000
    snapshot, = (target.parent / "backups/migrations").glob("*.sqlite3")
    with closing(sqlite3.connect(snapshot)) as old, closing(sqlite3.connect(target)) as new:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 2
        assert new.execute("PRAGMA user_version").fetchone()[0] >= 3
        assert new.execute("SELECT COUNT(*) FROM notes").fetchone() == old.execute("SELECT COUNT(*) FROM notes").fetchone()
    emit("upgrade", {"elapsed_ms": round(elapsed, 2), "snapshot_bytes": snapshot.stat().st_size,
                     "upgraded_bytes": target.stat().st_size})


def html_cost(directory, repetitions):
    from app.main import create_app
    from tests.client import TestClient
    from app.presentation import templates
    from app.services.projects import load_project_page
    path = directory / "ui.db"
    os.environ["PROJMEMO_DB_PATH"] = str(path)
    with TestClient(create_app()) as client:
        with closing(sqlite3.connect(path)) as connection, connection:
            seed(connection, 1, 20, 1)
        for count in (20, 250, 1000):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("DELETE FROM notes WHERE project_id=1")
                connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,?)",
                                       [(f"Benchmark note {number:04}", NOTE) for number in range(count)])
            db_times, template_times, total_times = [], [], []
            for _ in range(repetitions + 1):
                start = perf_counter()
                load_project_page(1)
                db_times.append((perf_counter() - start) * 1000)
                response = client.get("/projects/1")
                start = perf_counter()
                context = response.template.name
                templates.get_template(context).render(response.context)
                template_times.append((perf_counter() - start) * 1000)
                start = perf_counter()
                response = client.get("/projects/1")
                total_times.append((perf_counter() - start) * 1000)
            emit("html", {"notes": count, "bytes": len(response.content), "db_median_ms": round(median(db_times[1:]), 2),
                          "template_median_ms": round(median(template_times[1:]), 2), "request_median_ms": round(median(total_times[1:]), 2)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", type=int, default=1000)
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--html-repetitions", type=int, default=2)
    args = parser.parse_args()
    if args.projects < 2 or args.rows < 1 or args.repetitions < 1 or args.html_repetitions < 1:
        parser.error("Use at least 2 projects and positive row/repetition counts")
    with tempfile.TemporaryDirectory(prefix="projmemo-r03-benchmark-") as temporary:
        directory = Path(temporary)
        path = directory / "query.db"
        target = args.projects // 2
        with closing(sqlite3.connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            baseline_schema(connection)
            migration_history(connection)
            connection.execute("INSERT INTO schema_migrations(version,name) VALUES(2,'migration_history')")
            connection.execute("PRAGMA user_version=2")
            seed(connection, args.projects, args.rows, target)
            cases = queries(connection, target)
            before = measure(connection, cases, args.repetitions)
            before_size = path.stat().st_size
            upgrade_cost(path, directory)
            builds = []
            for statement in QUERY_INDEXES:
                start = perf_counter()
                connection.execute(statement)
                connection.commit()
                builds.append(round((perf_counter() - start) * 1000, 2))
            after = measure(connection, cases, args.repetitions)
            assert all(before[name]["digest"] == after[name]["digest"] for name in cases)
            emit("queries", {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                             "projects": args.projects, "rows_per_background_project": args.rows, "target_notes": 250,
                             "journal": connection.execute("PRAGMA journal_mode").fetchone()[0],
                             "before_bytes": before_size, "after_bytes": path.stat().st_size,
                             "index_build_ms": builds, "before": before, "after": after})
        emit("writer_wait", {"default_timeout_seconds": 5, "held_ms": 350, "observed_ms": writer_wait(path, .35)})
        html_cost(directory, args.html_repetitions)


if __name__ == "__main__":
    main()
