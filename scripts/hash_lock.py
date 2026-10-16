"""Add official PyPI archive hashes to pip-compile's exact, flat Windows pins.

This avoids downloading every platform's archive merely to compute its hash.
pip --require-hashes still verifies the actual archive during installation.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.request import urlopen

PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+_-]*)")
HASH = re.compile(r"[0-9a-f]{64}")


def normalized(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def fetch_hashes(pin):
    name, version = pin
    with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        metadata = json.load(response)
    if normalized(metadata["info"]["name"]) != normalized(name) or metadata["info"]["version"] != version:
        raise ValueError("PyPI metadata does not match the exact requested pin")
    hashes = sorted({archive["digests"]["sha256"] for archive in metadata["urls"]
                     if archive["packagetype"] in {"bdist_wheel", "sdist"}})
    if not hashes or not all(HASH.fullmatch(value) for value in hashes):
        raise ValueError("Missing or malformed PyPI SHA-256 metadata")
    return f"{normalized(name)}=={version} \\\n" + " \\\n".join(f"    --hash=sha256:{value}" for value in hashes) + "\n"


def render(pins_text):
    pins = []
    for line in pins_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match is None:
            raise ValueError("Expected flat exact pins; compile with --strip-extras --no-annotate first")
        pins.append(match.groups())
    if not pins or len({normalized(name) for name, _ in pins}) != len(pins):
        raise ValueError("Empty or duplicate package pins")
    with ThreadPoolExecutor(max_workers=6) as executor:
        blocks = list(executor.map(fetch_hashes, sorted(pins)))
    return ("# Generated Windows x64 / CPython 3.12 dependency closure.\n"
            "# pip-tools 7.6.2 exact pins + scripts/hash_lock.py PyPI SHA-256 metadata.\n"
            "# Edit .in files, not this lock. Install with --require-hashes.\n\n" + "\n".join(blocks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pins", type=Path)
    parser.add_argument("output", type=Path,
                        help="requirements.txt (runtime) or requirements/requirements-test.txt (tests)")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32":
        parser.error("Generate this lock on Windows with Python 3.12")
    # Resolve/fetch everything before replacing a previously usable lock.
    rendered = render(args.pins.read_text(encoding="utf-8"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=args.output.parent,
                                         prefix=".dependency-lock-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
