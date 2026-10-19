"""Shared Jinja presentation, localization, redirects and sanitized Markdown."""

from pathlib import Path
import nh3
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markdown import markdown as render_markdown

from .i18n import get_language, translate_error, translator
from .options import (
    STATUS_OPTIONS, URL_TYPES, NOTE_CATEGORIES, PRIORITIES, CHECKLIST_CATEGORIES,
    ENVIRONMENTS, ACCESS_ACCOUNT_CATEGORIES, ACCESS_ENVIRONMENTS,
    status_label, url_type_label, note_category_label, checklist_category_label,
    priority_label, environment_label, access_environment_label, access_account_category_label,
)
from .web_security import csrf_input
from .markdown_editor import editor_templates

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals.update(
    editor_templates=editor_templates,
    csrf_input=csrf_input, status_label=status_label, url_type_label=url_type_label,
    note_category_label=note_category_label, checklist_category_label=checklist_category_label,
    priority_label=priority_label, environment_label=environment_label,
    access_environment_label=access_environment_label,
    access_account_category_label=access_account_category_label,
)


def page_context(request: Request, **values: object) -> dict[str, object]:
    language = get_language(request)
    t = translator(request)
    option_groups = {
        "status_options": (STATUS_OPTIONS, "status_label"),
        "url_types": (URL_TYPES, "url_type_label"),
        "note_categories": (NOTE_CATEGORIES, "note_category_label"),
        "priorities": (PRIORITIES, "priority_label"),
        "checklist_categories": (CHECKLIST_CATEGORIES, "checklist_category_label"),
        "environments": (ENVIRONMENTS, "environment_label"),
        "access_account_categories": (ACCESS_ACCOUNT_CATEGORIES, "access_account_category_label"),
        "access_environments": (ACCESS_ENVIRONMENTS, "access_environment_label"),
    }
    context = {
        "request": request,
        "language": language,
        "t": t,
        "csrf_token": request.state.csrf_token,
        "return_to": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        **values,
    }
    for name, (options, label_function) in option_groups.items():
        localized = [(value, t(label)) for value, label in options]
        context[name] = localized
        labels = dict(localized)
        context[label_function] = lambda value, labels=labels: labels.get(value, value)
    if "form_title" in values:
        context["form_title"] = t(str(values["form_title"]))
    if "error" in values:
        context["error"] = translate_error(str(values["error"]), language)
    return context


MARKDOWN_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "strong", "table", "tbody",
    "td", "th", "thead", "tr", "ul",
}
MARKDOWN_SANITIZER = nh3.Cleaner(
    tags=MARKDOWN_ALLOWED_TAGS,
    attributes={"a": {"href", "title"}, "td": {"align"}, "th": {"align"}},
    url_schemes={"http", "https", "mailto"},
    strip_comments=True,
)


def markdown_filter(value: str) -> str:
    rendered_html = render_markdown(
        value or "",
        extensions=["fenced_code", "tables", "nl2br"],
    )
    return MARKDOWN_SANITIZER.clean(rendered_html)


templates.env.filters["markdown"] = markdown_filter


PREVIEW_SANITIZER = nh3.Cleaner(tags=MARKDOWN_ALLOWED_TAGS, attributes={}, strip_comments=True, link_rel=None)
PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; sandbox"


def preview_document(value: str, language: str) -> str:
    # A second allowlist removes navigation targets; the iframe has no permissions.
    body = PREVIEW_SANITIZER.clean(markdown_filter(value))
    return (f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{PREVIEW_CSP.removesuffix("; sandbox")}">'
            '<style>body{font:15px/1.7 system-ui,sans-serif;color:#243047;padding:16px;margin:0;'
            'overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f3f5fa;padding:12px}'
            'table{border-collapse:collapse;max-width:100%}td,th{border:1px solid #ccd3e2;padding:6px}'
            'h1,h2,h3{line-height:1.4}blockquote{border-left:3px solid #6273ef;padding-left:12px}</style>'
            f'</head><body>{body}</body></html>')


def redirect_to_project(project_id: int) -> RedirectResponse:
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
