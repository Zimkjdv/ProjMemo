"""Shared write validation. Existing database values are not rewritten on read."""

import ipaddress
import re
from urllib.parse import urlsplit

from .errors import FieldValidationError
from .options import (STATUS_OPTIONS, URL_TYPES, NOTE_CATEGORIES, PRIORITIES,
                      CHECKLIST_CATEGORIES, ENVIRONMENTS, ACCESS_ACCOUNT_CATEGORIES, ACCESS_ENVIRONMENTS)

RULES = {
    "project": {"name": 200, "description": 10000, "status": STATUS_OPTIONS, "owner": 1000, "tags": 1000},
    "url": {"type": URL_TYPES, "title": 200, "url": 4096, "note": 10000},
    "note": {"category": NOTE_CATEGORIES, "title": 200, "content_markdown": 100000, "priority": PRIORITIES},
    "checklist": {"category": CHECKLIST_CATEGORIES, "title": 200, "description": 10000, "owner": 1000, "note": 10000},
    "environment": {"key": 256, "environment": ENVIRONMENTS, "description": 10000, "source_or_owner": 1000},
    "account": {"label": 200, "category": ACCESS_ACCOUNT_CATEGORIES, "environment": ACCESS_ENVIRONMENTS,
                "endpoint": 4096, "database_name": 256, "username": 1000, "role_scope": 10000,
                "purpose": 10000, "owner": 1000, "secret_reference": 10000, "secret_value": 4096},
}
REQUIRED = {
    "name": "專案名稱不可為空白", "title": "此欄位不可為空白。", "url": "此欄位不可為空白。",
    "content_markdown": "此欄位不可為空白。", "key": "環境變數名稱不可為空白", "label": "帳號或服務名稱不可為空白",
}


def normalize_tokens(value: str) -> str:
    seen, result = set(), []
    for token in re.split(r"[,，、;；\r\n]+", value):
        token = token.strip()
        if token and token.casefold() not in seen:
            seen.add(token.casefold())
            result.append(token)
    return ", ".join(result)


def valid_web_url(value: str) -> bool:
    if re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return False
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username is not None:
            return False
        if parts.port is not None and not 1 <= parts.port <= 65535:
            return False
        host = parts.hostname.rstrip(".")
        if ":" in host or re.fullmatch(r"[\d.]+", host):
            ipaddress.ip_address(host)
        else:
            host = host.encode("idna").decode("ascii")
            if len(host) > 253 or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", part)
                                          for part in host.split(".")):
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def normalize_fields(kind: str, values: dict) -> tuple:
    result, errors = {}, {}
    for field, rule in RULES[kind].items():
        value = values[field]
        if not isinstance(value, str):
            errors[field] = "此欄位格式不正確。"
            continue
        # Password bytes are never normalized, trimmed, or included in messages.
        cleaned = value if field == "secret_value" else value.strip()
        if field != "secret_value" and "\x00" in cleaned:
            errors[field] = "此欄位格式不正確。"
        if isinstance(rule, list):
            if cleaned not in dict(rule):
                errors[field] = "請選擇有效選項。"
        elif len(cleaned) > rule:
            errors[field] = f"此欄位不可超過 {rule} 個字元。"
        if field in REQUIRED and not cleaned:
            errors[field] = REQUIRED[field]
        if field in {"owner", "tags"}:
            cleaned = normalize_tokens(cleaned)
            if len(cleaned) > rule:
                errors[field] = f"此欄位不可超過 {rule} 個字元。"
        if field == "url" and cleaned and not valid_web_url(cleaned):
            errors[field] = "請輸入有效的 HTTP／HTTPS 網址（不可包含帳號密碼）。"
        result[field] = cleaned
    if errors:
        raise FieldValidationError(errors)
    return tuple(result.values())
