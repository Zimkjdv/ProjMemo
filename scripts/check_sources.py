"""Read-only baseline formatting, Python/JSON/YAML and JavaScript syntax checks."""

import argparse
import ast
import json
from pathlib import Path
import shutil
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".py", ".js", ".cjs", ".json", ".html", ".css", ".yml", ".yaml"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def check(root):
    problems, scripts, count = [], [], 0
    for directory in ("app", "scripts", "tests", ".github"):
        for path in sorted((root / directory).rglob("*")):
            if {"__pycache__", "node_modules"}.intersection(path.parts) or path.suffix not in SUFFIXES:
                continue
            label = path.relative_to(root).as_posix()
            if path.is_symlink() or path.is_junction():
                problems.append(f"source link is not allowed: {label}")
                continue
            if not path.is_file():
                continue
            count += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                problems.append(f"unreadable UTF-8 source: {label}")
                continue
            if text and not text.endswith("\n"):
                problems.append(f"missing final newline: {label}")
            for line_number, line in enumerate(text.splitlines(), 1):
                if line.rstrip(" \t") != line:
                    problems.append(f"trailing whitespace: {label}:{line_number}")
            try:
                if path.suffix == ".py":
                    ast.parse(text, filename=label)
                elif path.suffix == ".json":
                    json.loads(text, object_pairs_hook=unique_object)
                elif path.suffix in {".yml", ".yaml"}:
                    yaml.safe_load(text)
                elif path.suffix in {".js", ".cjs"}:
                    scripts.append(path)
            except (SyntaxError, ValueError, yaml.YAMLError):
                problems.append(f"invalid source syntax: {label}")
    if count == 0:
        problems.append("no source files found")
    node = shutil.which("node")
    if scripts and node is None:
        problems.append("Node.js is required for JavaScript syntax checks")
    elif node:
        for path in scripts:
            try:
                result = subprocess.run([node, "--check", str(path.resolve())], cwd=root,
                                        capture_output=True, timeout=20)
                if result.returncode:
                    problems.append(f"invalid JavaScript syntax: {path.relative_to(root).as_posix()}")
            except (OSError, subprocess.TimeoutExpired):
                problems.append(f"JavaScript syntax check failed: {path.relative_to(root).as_posix()}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    problems = check(args.root.resolve())
    if problems:
        print("\n".join(problems))
        return 1
    print("Source checks passed: UTF-8, final newlines, whitespace and syntax.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
