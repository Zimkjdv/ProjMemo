"""Disposable loopback-only browser fixture. Never import this in the application."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading


def main():
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
            server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error", access_log=False))
            def stop_on_eof():
                sys.stdin.read()
                server.should_exit = True
            threading.Thread(target=stop_on_eof, daemon=True).start()
            server.run(sockets=[reserved])


if __name__ == "__main__":
    main()
