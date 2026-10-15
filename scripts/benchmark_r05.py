"""Measure UI paging versus full-template rendering, with disposable fake data."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import create_app
from app.presentation import templates
from app.services.projects import load_project_data, load_project_page
from scripts.benchmark_r03 import NOTE
from tests.client import TestClient


def main():
    previous = os.environ.get("PROJMEMO_DB_PATH")
    try:
        with TemporaryDirectory(prefix="projmemo-r05-") as directory:
            path = Path(directory) / "fixture.db"
            os.environ["PROJMEMO_DB_PATH"] = str(path)
            with TestClient(create_app()) as client:
                client.post("/projects/new", data={"name": "Synthetic benchmark"})
                for count in (250, 1000):
                    with closing(sqlite3.connect(path)) as connection, connection:
                        connection.execute("DELETE FROM notes")
                        connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,?)",
                            [(f"Note {number:04}", NOTE) for number in range(count)])
                    for size in (10, 20, 50):
                        request_times, partial_times, full_times = [], [], []
                        for attempt in range(4):
                            start = perf_counter()
                            page = client.get(f"/projects/1?notes_size={size}")
                            request_ms = (perf_counter() - start) * 1000
                            start = perf_counter()
                            fragment = client.get(f"/projects/1?notes_size={size}&notes_page={count // size}",
                                headers={"X-ProjMemo-Fragment": "notes"})
                            partial_ms = (perf_counter() - start) * 1000
                            # Same current template and related data, but all notes, as a
                            # comparison model; not a claim about old release timings.
                            context = dict(page.context)
                            context.update(load_project_page(1))
                            context.pop("note_page", None)
                            start = perf_counter()
                            full_html = templates.get_template("project_detail.html").render(context)
                            full_ms = (perf_counter() - start) * 1000
                            if attempt:
                                request_times.append(request_ms); partial_times.append(partial_ms); full_times.append(full_ms)
                        assert len(load_project_data(1).notes) == count
                        print(json.dumps({"notes": count, "size": size, "ui_bytes": len(page.content),
                            "fragment_bytes": len(fragment.content), "full_template_bytes": len(full_html.encode()),
                            "ui_request_ms": round(median(request_times), 2),
                            "fragment_request_ms": round(median(partial_times), 2),
                            "full_template_ms": round(median(full_times), 2)}, ensure_ascii=True), flush=True)
    finally:
        if previous is None:
            os.environ.pop("PROJMEMO_DB_PATH", None)
        else:
            os.environ["PROJMEMO_DB_PATH"] = previous


if __name__ == "__main__":
    main()
