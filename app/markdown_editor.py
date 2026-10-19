"""Built-in, versioned note templates; never interpolate project data or secrets."""

import json
from pathlib import Path

from .errors import ApplicationError


NOTE_TEMPLATES = json.loads((Path(__file__).parent / "locales/note-templates.json").read_text(encoding="utf-8"))


def editor_templates(language: str):
    return NOTE_TEMPLATES[language if language in {"zh-Hant", "en"} else "zh-Hant"]


def validate_preview(content: str) -> str:
    if len(content) > 100_000 or "\x00" in content:
        raise ApplicationError(400, "預覽內容不可超過 100000 個字元或包含空字元。")
    return content
