"""Read-only catalog checks. Run from any cwd; never import app or open its DB."""

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
from string import Formatter

from jinja2 import Environment, nodes

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3400-\u9fff]")
EXPORT_ONLY = {"markdown_export.py", "pdf_export.py"}
ERRORS = {"ApplicationError", "HTTPException", "VaultError", "VaultNotInitialized",
          "VaultAlreadyInitialized", "InvalidMasterPassword", "VaultRateLimited",
          "BackupValidationError", "BackupRestoreError", "SchemaValidationError", "DatabaseBusyError"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate catalog key: {key}")
        result[key] = value
    return result


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def placeholders(message):
    result = Counter()
    for _, field, spec, conversion in Formatter().parse(message):
        if field is not None:
            if not field.isidentifier():
                raise ValueError("Only named placeholders are supported")
            result[(field, spec, conversion)] += 1
    return result


def literal_messages(node):
    if isinstance(node, ast.JoinedStr):
        return  # A fragment of an f-string is not a complete message.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    for child in ast.iter_child_nodes(node):
        yield from literal_messages(child)


def python_inventory(app):
    used, required, dynamic = set(), set(), set()
    for path in sorted(app.rglob("*.py")):
        if path.name in EXPORT_ONLY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant) for target in node.targets if isinstance(target, ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.add(node.value)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                values = []
                if name in {"t", "translate", "translate_error"}:
                    values = node.args[:1]
                elif name in ERRORS:
                    values = [*node.args, *(keyword.value for keyword in node.keywords)]
                for value in values:
                    required.update(message for message in literal_messages(value) if CJK.search(message))
            if path.name != "i18n.py":
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and CJK.search(node.value.value):
                    required.add(node.value.value)
                if isinstance(node, ast.Dict):
                    required.update(value.value for value in [*node.keys, *node.values]
                                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and CJK.search(value.value))
            if isinstance(node, ast.JoinedStr) and any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                    and CJK.search(part.value) for part in node.values):
                pattern, resolved, complete = "", "", True
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        pattern += str(part.value)
                        resolved += str(part.value)
                    elif isinstance(part, ast.FormattedValue):
                        pattern += "{" + ast.unparse(part.value) + "}"
                        if isinstance(part.value, ast.Name) and part.value.id in constants:
                            resolved += str(constants[part.value.id])
                        else:
                            complete = False
                if CJK.search(pattern):
                    if complete:
                        required.add(resolved)
                        used.add(resolved)
                    else:
                        dynamic.add((path.relative_to(app).as_posix(), pattern))
        if path.name == "options.py":
            for node in tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
                    for pair in ast.literal_eval(node.value):
                        required.add(pair[1])
    return used, required, dynamic


def template_inventory(app):
    used, required, problems = set(), set(), []
    for path in sorted((app / "templates").rglob("*.html")):
        tree = Environment().parse(path.read_text(encoding="utf-8"))
        for value in tree.find_all(nodes.Const):
            if isinstance(value.value, str):
                used.add(value.value)
                if CJK.search(value.value) and value.value != "繁中":
                    required.add(value.value)
        for call in tree.find_all(nodes.Call):
            if isinstance(call.node, nodes.Name) and call.node.name == "t" and call.args:
                required.update(value.value for value in [call.args[0], *call.args[0].find_all(nodes.Const)]
                                if isinstance(value, nodes.Const) and isinstance(value.value, str))
        for literal in tree.find_all(nodes.TemplateData):
            if CJK.search(literal.data.replace("繁中", "")):
                problems.append(f"untranslated template text: {path.relative_to(app)}:{literal.lineno}")
    return used, required, problems


def check(app):
    catalog = load_json(app / "locales/en.json")
    policy = load_json(app / "locales/catalog-policy.json")
    used, required, dynamic = python_inventory(app)
    template_used, template_required, problems = template_inventory(app)
    used |= template_used
    required |= template_required
    declared = set()
    for entry in policy["normalized_errors"]:
        source, pattern, key = entry["source"], entry["pattern"], entry["key"]
        declared.add((source, pattern))
        if not entry["reason"].strip() or (source, pattern) not in dynamic:
            problems.append(f"stale dynamic declaration: {source}: {pattern}")
        if key not in used:
            problems.append(f"dynamic normalization target is not in source: {key}")
        required.add(key)
        used.add(key)
    for source, pattern in sorted(dynamic - declared):
        problems.append(f"unregistered dynamic message: {source}: {pattern}")
    retained = policy["retained_unused"]
    identities = policy["identity_keys"]
    for key, reason in identities.items():
        if CJK.search(key) or key not in used or key not in required or key in catalog or not reason.strip():
            problems.append(f"invalid/stale identity key: {key}")
    for key, reason in retained.items():
        if key not in catalog or key in used or not isinstance(reason, str) or not reason.strip():
            problems.append(f"invalid/stale retained key: {key}")
    for key in sorted(required - catalog.keys() - identities.keys()):
        problems.append(f"missing: {key}")
    for key, value in catalog.items():
        if not isinstance(value, str) or not value.strip():
            problems.append(f"empty/non-string translation: {key}")
            continue
        base = key.removesuffix("::one")
        if base not in used and key not in retained:
            problems.append(f"unused: {key}")
        if key.endswith("::one") and (base not in catalog or "{count}" not in base):
            problems.append(f"invalid plural variant: {key}")
        try:
            if placeholders(base) != placeholders(value):
                problems.append(f"placeholder mismatch: {key}")
        except ValueError as error:
            problems.append(f"invalid format: {key}: {error}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=ROOT / "app")
    args = parser.parse_args(argv)
    try:
        problems = check(args.app_dir)
    except (OSError, ValueError, KeyError, SyntaxError) as error:
        print(f"Catalog check failed: {error}")
        return 1
    if problems:
        print("\n".join(problems))
        return 1
    print("Catalog check passed: no missing/unused keys, format drift or unregistered dynamic messages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
