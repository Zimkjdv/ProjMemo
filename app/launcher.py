"""Single-worker loopback launcher handing an already bound socket to Uvicorn."""

import argparse
import errno
import importlib
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
MAX_PORT_ATTEMPTS = 100


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--check", action="store_true", help="Check dependencies without opening a database")
    parser.add_argument("--dev", action="store_true", help="Development reload, one application worker")
    parser.add_argument("--port", type=int, help="First port to try (otherwise PROJMEMO_PORT or 8000)")
    parser.add_argument("--port-end", type=int, help="Last port to try, at most 100 ports including the first")
    args = parser.parse_args(argv)
    if args.port is None:
        try:
            args.port = int(os.environ.get("PROJMEMO_PORT", "8000"))
        except ValueError:
            parser.error("PROJMEMO_PORT must be an integer between 1 and 65535")
    if not 1 <= args.port <= 65535:
        parser.error("The first port must be between 1 and 65535")
    if args.port_end is None:
        args.port_end = min(65535, args.port + MAX_PORT_ATTEMPTS - 1)
    if not args.port <= args.port_end <= min(65535, args.port + MAX_PORT_ATTEMPTS - 1):
        parser.error("The last port must be at or above the first, with at most 100 attempts")
    return args


def bind_local_socket(first, last):
    # Keep ownership through server startup: never probe, release, and rebind.
    for port in range(first, last + 1):
        reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reserved.bind((HOST, port))
            reserved.listen(2048)
            reserved.set_inheritable(True)
            return reserved
        except OSError as error:
            reserved.close()
            if error.errno not in {errno.EADDRINUSE, errno.EACCES, 10013, 10048}:
                raise
    raise RuntimeError(f"No available local port in {first}-{last}. Choose another range.")


def check_dependencies():
    if sys.version_info[:2] != (3, 12):
        print("ERROR: Python 3.12 is required. Preserve data and repair .venv with setup-local.bat.", file=sys.stderr)
        return False
    try:
        importlib.import_module("uvicorn")
        importlib.import_module("app.main")
    except Exception:
        print("ERROR: Local dependencies are missing or incompatible. Run setup-local.bat and resolve its errors.", file=sys.stderr)
        return False
    return True


def serve(reserved, *, development=False):
    import uvicorn
    from uvicorn.supervisors import ChangeReload

    port = reserved.getsockname()[1]
    config = uvicorn.Config(
        "app.main:app", host=HOST, port=port, reload=development, workers=1,
        reload_dirs=[str(ROOT / "app")] if development else None,
        reload_excludes=[str(ROOT / name) for name in ("data", ".venv", "tests", ".git")] if development else None,
    )
    server = uvicorn.Server(config)
    mode = "development reload" if development else "normal"
    print(f"ProjMemo [{mode}], single worker: http://{HOST}:{port}/ (waiting for application startup)", flush=True)
    if development:
        ChangeReload(config, target=server.run, sockets=[reserved]).run()
        return 0
    server.run(sockets=[reserved])
    return 0 if server.started else 3


def main(argv=None):
    args = arguments(argv)
    os.chdir(ROOT)
    if not check_dependencies():
        return 2
    if args.check:
        print("Local environment is ready. No packages were installed and no database was opened.")
        return 0
    reserved = None
    try:
        reserved = bind_local_socket(args.port, args.port_end)
        if reserved.getsockname()[1] != args.port:
            print(f"Requested port {args.port} is unavailable; selected {reserved.getsockname()[1]}.", flush=True)
        return serve(reserved, development=args.dev)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError):
        print(f"ERROR: Cannot start ProjMemo on loopback ports {args.port}-{args.port_end}. Check port availability and local permissions.", file=sys.stderr)
        return 2
    finally:
        if reserved is not None:
            reserved.close()


if __name__ == "__main__":
    raise SystemExit(main())
