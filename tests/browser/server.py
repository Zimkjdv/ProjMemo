"""Disposable loopback-only browser fixture. Never import this in the application."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading


def main():
    if os.name == "nt":
        # Python 3.12 Proactor's reset callback can raise WinError 10054 before
        # Server._detach(), leaving wait_closed() pending. This is test-process
        # policy only, not a change to the user's launcher or application.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    root = Path(__file__).resolve().parents[2]
    parent = root / "data"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r08-browser-", dir=parent) as directory:
        os.environ["PROJMEMO_DB_PATH"] = str(Path(directory) / "fixture.db")
        from app.db import init_db
        from app.main import create_app
        from app.services.projects import create_project
        from app.services.content import add_note, add_url
        import uvicorn

        init_db()
        create_project(name="Browser fixture / 瀏覽器範例", description="Isolated data only")
        add_url(project_id=1, title="Fixture URL", url="https://example.invalid/path")
        for number in range(55):
            add_note(project_id=1, title=f"Fixture note {number:02}",
                     content_markdown=f"備註 {number}\n\n```python\nprint('fixture')\n```\n")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            if os.name == "nt":
                reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reserved.bind(("127.0.0.1", 0))
            reserved.listen(128)
            print(json.dumps({"url": f"http://127.0.0.1:{reserved.getsockname()[1]}"}), flush=True)
            class FixtureServer(uvicorn.Server):
                async def shutdown(self, sockets=None):
                    print("fixture: shutdown started", file=sys.stderr, flush=True)
                    await super().shutdown(sockets)
                    print("fixture: shutdown finished", file=sys.stderr, flush=True)
            server = FixtureServer(uvicorn.Config(create_app(), log_level="error", access_log=False))
            def stop_on_eof():
                sys.stdin.read()
                print("fixture: EOF received", file=sys.stderr, flush=True)
                server.should_exit = True
            threading.Thread(target=stop_on_eof, daemon=True).start()
            server.run(sockets=[reserved])
            print("fixture: server returned", file=sys.stderr, flush=True)
    print("fixture: temporary directory removed", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
