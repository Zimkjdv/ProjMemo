"""Disposable desktop acceptance server; never imported by the application.

Run with python -m tests.desktop_fixture. EOF on stdin stops the server and
removes its private database. No existing database or browser permissions change.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading


COPY_URL = "https://portal.example.invalid/" + "long-readable-path/" * 45 + "?q=%E6%B8%AC%E8%A9%A6&x=1&x=2#END"
COPY_ENDPOINT = "db.example.invalid:5432/" + "long-database-path/" * 40 + "END"
COPY_USERNAME = "fixture-user-" * 55 + "測試_END"
COPY_CODE = '# 假資料 / fixture only\nfor name in ["one", "two"]:\n    print("<tag> &", name)\n\n# END\n'


def seed(runtime):
    """Called only after the caller selects a private fixture database."""
    from app.services.accounts import add_access_account
    from app.services.content import add_checklist_item, add_environment_variable, add_note, add_url
    from app.services.projects import create_project

    projects = {}
    for profile, note_count, account_count in (("empty", 0, 0), ("mixed", 4, 2), ("large", 250, 30)):
        project_id = create_project(name=f"R06 {profile} / 隔離假資料", owner="Fixture team, 範例團隊",
            tags="UI, fixture, 假資料", description="Disposable desktop fixture. 不含真實帳密；不操作正式資料。")
        projects[profile] = project_id
        if profile == "empty":
            continue
        for kind in ("production", "staging", "git"):
            add_url(project_id=project_id, type=kind, title=f"Fixture {kind}", url=COPY_URL,
                    note="Example only; do not open the invalid domain.")
        for number in range(note_count):
            category = ("note", "caution", "known_issue", "workaround")[number % 4]
            body = ("Long bilingual note. 中文長文、注意事項與部署步驟。\n\n" * 12
                    if number % 4 else "A short note. 短備註。\n\n")
            if number == note_count - 1:
                body += f"```python\n{COPY_CODE}```\n"
            add_note(project_id=project_id, category=category, title=f"Fixture note {number:03}",
                     content_markdown=body, priority="critical" if number % 4 == 1 else "normal")
        for number in range(account_count):
            add_access_account(runtime=runtime, token=None, project_id=project_id,
                label=f"Fixture account {number:02}", category="database", environment="test",
                endpoint=COPY_ENDPOINT, username=COPY_USERNAME, database_name="fixture_db",
                role_scope="Read-only fixture", purpose="Desktop acceptance only", owner="Fixture team",
                secret_reference="External fixture reference; no actual secret")
        add_checklist_item(project_id=project_id, category="deployment", title="Fixture deployment checks",
                           description="Review environment / 確認環境", owner="Fixture team")
        add_environment_variable(project_id=project_id, key="FIXTURE_CONNECTION", description="Description only",
                                 source_or_owner="External fixture reference", is_secret=True)
    return projects


class ClipboardFixture:
    """Page-local failure simulation, not a browser permission change.

    Normal mode is completely unwrapped. These two opt-in modes only verify the
    rendered fallback message; they do not certify a real OS permission denial.
    """

    def __init__(self, app, mode):
        if mode not in {"denied", "unavailable"}:
            raise ValueError("Only explicit failure fixture modes are supported")
        self.app, self.mode = app, mode

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start, chunks = None, []

        async def capture(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                return await send(message)
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            headers = list(start["headers"])
            if any(key.lower() == b"content-type" and b"text/html" in value for key, value in headers):
                value = ("{writeText:()=>Promise.reject(new DOMException('Fixture denied','NotAllowedError'))}"
                         if self.mode == "denied" else "undefined")
                script = (f'<script data-desktop-clipboard-fixture="{self.mode}">'
                          f"Object.defineProperty(navigator,'clipboard',{{configurable:true,value:{value}}});"
                          "</script>").encode()
                body = body.replace(b"<head>", b"<head>" + script, 1)
                headers = [(key, value) for key, value in headers if key.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, capture)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clipboard", choices=("normal", "denied", "unavailable"), default="normal")
    args = parser.parse_args(argv)
    parent = Path(__file__).resolve().parents[1] / "data"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r06-desktop-", dir=parent) as directory:
        # Always override before importing app/DB modules; no --db or --host escape hatch.
        os.environ["PROJMEMO_DB_PATH"] = str(Path(directory) / "fixture.db")
        from app.db import init_db
        from app.main import create_app
        import uvicorn

        init_db()
        app = create_app()
        projects = seed(app.state.runtime)
        target = app if args.clipboard == "normal" else ClipboardFixture(app, args.clipboard)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            if os.name == "nt":
                reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reserved.bind(("127.0.0.1", 0))
            reserved.listen(128)
            print(json.dumps({"url": f"http://127.0.0.1:{reserved.getsockname()[1]}",
                              "projects": projects, "clipboard": args.clipboard}), flush=True)
            server = uvicorn.Server(uvicorn.Config(target, log_level="error", access_log=False))

            def stop_on_eof():
                sys.stdin.read()
                server.should_exit = True

            threading.Thread(target=stop_on_eof, daemon=True).start()
            server.run(sockets=[reserved])


if __name__ == "__main__":
    main()
