"""Request-scoped UI translations; project data and export content stay unchanged."""

from functools import partial
import json
from pathlib import Path
import re

from fastapi import Request


DEFAULT_LANGUAGE = "zh-Hant"
LANGUAGES = {"zh-Hant": "繁體中文", "en": "English"}
LANGUAGE_COOKIE = "projmemo_language"
EN_MESSAGES = json.loads((Path(__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
ZH_MESSAGES = {
    "Git Repository": "程式碼庫",
    "Known Issue": "已知問題",
    "Workaround": "替代方案",
    "Local": "本機",
    "Staging": "測試環境",
    "Production": "正式環境",
}


def get_language(request: Request) -> str:
    language = request.cookies.get(LANGUAGE_COOKIE, DEFAULT_LANGUAGE)
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def translate(message: str, language: str = DEFAULT_LANGUAGE, **values: object) -> str:
    catalog = EN_MESSAGES if language == "en" else ZH_MESSAGES
    key = f"{message}::one" if language == "en" and values.get("count") == 1 else message
    translated = catalog.get(key, catalog.get(message, message))
    return translated.format(**values) if values else translated


def translator(request: Request):
    return partial(translate, language=get_language(request))


def translate_error(message: str, language: str) -> str:
    """Translate application errors, including the backup schema's table name."""
    match = re.fullmatch(r"備份檔的「([^」]+)」資料表欄位不完整，無法還原。", message)
    if match:
        return translate("備份檔的「{table}」資料表欄位不完整，無法還原。", language, table=match[1])
    return translate(message, language)
