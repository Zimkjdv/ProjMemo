"""Recover native HTML forms without persisting drafts or echoing secrets.

Only controls already present in the server template may be restored. The HTML
parser operates on trusted rendered markup; submitted strings are always escaped.
JSON consumers keep the normal error contract.
"""

from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from .errors import ApplicationError
from .i18n import translator, translate_error, get_language
from .web_security import NO_STORE_HEADERS

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SENSITIVE = {"master_password", "confirm_password", "secret_value", "delete_secret"}
LEGACY_FIELDS = {
    "專案名稱不可為空白": ("name",), "URL 標題與網址不可為空白": ("title", "url"),
    "網址必須以 http:// 或 https:// 開頭": ("url",),
    "備註標題與內容不可為空白": ("title", "content_markdown"),
    "交接項目不可為空白": ("title",), "環境變數名稱不可為空白": ("key",),
    "帳號或服務名稱不可為空白": ("label",),
}


class Element:
    def __init__(self, tag="", attrs=(), parent=None, raw=None):
        self.tag, self.attrs, self.parent, self.raw = tag, dict(attrs), parent, raw
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def html(self):
        if not self.tag:
            return "".join(child.html() if isinstance(child, Element) else child for child in self.children)
        start = self.raw or "<" + self.tag + "".join(
            f' {key}' if value is None else f' {key}="{escape(str(value), quote=True)}"'
            for key, value in self.attrs.items()) + ">"
        return start if self.tag in VOID else start + "".join(
            child.html() if isinstance(child, Element) else child for child in self.children) + f"</{self.tag}>"


class FormDocument(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.root = self.current = Element()
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.current, self.get_starttag_text())
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    def handle_comment(self, data):
        self.handle_data(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.handle_data(f"<!{decl}>")


def restore_form(markup, action, values, message, fields, t, recovery_url=None):
    document = FormDocument(markup)
    if recovery_url:
        for node in document.root.walk():
            if node.tag == "html":
                node.attrs["data-recovery-url"] = recovery_url
                node.raw = None
            if node.tag == "input" and node.attrs.get("name") == "return_to":
                node.attrs["value"] = recovery_url
                node.raw = None
            if node.attrs.get("id") == "project-content" and values.get("_detail_view") in {"cards", "list"}:
                node.attrs["data-return-view"] = values["_detail_view"]
                node.raw = None
    form = next((node for node in document.root.walk()
                 if node.tag == "form" and node.attrs.get("action") == action), None)
    if form is None:
        return None
    ancestor = form.parent
    while ancestor:
        if ancestor.tag == "details":
            ancestor.attrs["open"] = None
            ancestor.raw = None
        ancestor = ancestor.parent
    form.attrs["data-recovered-form"] = "true"
    form.raw = None
    # Snapshot controls before inserting our feedback nodes.
    for index, node in enumerate(list(form.walk())):
        name = node.attrs.get("name")
        if node.tag not in {"input", "select", "textarea"} or not name:
            continue
        kind = node.attrs.get("type", "text")
        if name in SENSITIVE or kind in {"password", "file"}:
            node.attrs.pop("value", None)
            node.attrs.pop("checked", None)
            node.raw = None
        elif name == "_submission_token" and isinstance(values.get(name), str):
            node.attrs["value"] = values[name]
            node.raw = None
        elif kind not in {"hidden", "submit", "button"}:
            value = values.get(name, "")
            value = value if isinstance(value, str) else ""
            node.raw = None
            if node.tag == "textarea":
                node.children = [escape(value)]
            elif node.tag == "select":
                for option in node.walk():
                    if option.tag == "option":
                        option.raw = None
                        option.attrs.pop("selected", None)
                        if option.attrs.get("value") == value:
                            option.attrs["selected"] = None
            elif kind in {"checkbox", "radio"}:
                node.attrs.pop("checked", None)
                if value == node.attrs.get("value", "on"):
                    node.attrs["checked"] = None
            else:
                node.attrs["value"] = value
        if name in fields:
            error_id = f"form-error-{index}"
            node.attrs["aria-invalid"] = "true"
            node.attrs["aria-describedby"] = (node.attrs.get("aria-describedby", "") + " " + error_id).strip()
            node.raw = None
            node.parent.children.insert(node.parent.children.index(node) + 1,
                f'<small class="field-error" id="{error_id}">{escape(t(fields[name]))}</small>')
    form.children.insert(0, '<div class="form-feedback" role="alert" tabindex="-1" autofocus>'
                         f'<strong>{escape(t("請檢查輸入資料"))}</strong><p>{escape(message)}</p>'
                         f'<small>{escape(t("非敏感輸入已保留；密碼請重新輸入。"))}</small></div>')
    return document.root.html()


async def recover_form_error(request: Request, error, *, fields=None):
    if request.method != "POST" or "text/html" not in request.headers.get("accept", ""):
        return None
    from .routers import projects, vault, backups
    from .services.projects import project_for_item
    path = request.url.path
    try:
        values = await request.form()
        request.state.notes_page = values.get("_notes_page", "1")
        request.state.notes_size = values.get("_notes_size", "20")
        if path == "/projects/new":
            response = projects.new_project(request)
        elif match := re.fullmatch(r"/projects/(\d+)/lifecycle/(archive|unarchive|trash|restore|purge)", path):
            response = projects.manage_project(request, int(match[1]))
            # Always require fresh confirmation after an error, especially stale revisions.
            values = dict(values)
            values["confirmation_name"] = ""
            values["confirmed"] = ""
        elif match := re.fullmatch(r"/projects/(\d+)/edit", path):
            response = projects.edit_project(request, int(match[1]))
        elif match := re.fullmatch(r"/projects/(\d+)/(urls|notes|checklist|environment-variables|accounts|export)", path):
            response = projects.show_project(request, int(match[1]))
        elif match := re.fullmatch(r"/(urls|notes|checklist|environment-variables|accounts)/(\d+)/(edit|delete|toggle)", path):
            if match[1] == "notes":
                request.state.editing_note_id = int(match[2])
            response = projects.show_project(request, project_for_item(match[1], int(match[2])))
        elif path.startswith("/settings/vault/"):
            response = vault.vault_page(request)
        elif path == "/settings/backup/restore":
            response = backups._backup_page(request)
        else:
            return None
        t = translator(request)
        errors = fields or getattr(error, "fields", {}) or {
            name: error.detail for name in LEGACY_FIELDS.get(error.detail, ())}
        localize = lambda message: translate_error(message, get_language(request))
        project = response.context.get("project")
        recovery_url = ("/settings/vault" if path.startswith("/settings/vault/") else
                        "/settings/backup" if path.startswith("/settings/backup/") else
                        f'/projects/{project["id"]}/manage' if "/lifecycle/" in path and project else
                        f'/projects/{project["id"]}' + ("/edit" if path.endswith("/edit") and path.startswith("/projects/") else "")
                        if project else "/projects/new")
        if pager := response.context.get("note_page"):
            recovery_url += "?" + urlencode({"notes_page": pager["number"], "notes_size": pager["size"],
                "detail_view": values.get("_detail_view") if values.get("_detail_view") in {"cards", "list"} else "cards"})
        markup = restore_form(response.body.decode("utf-8"), path, values, localize(error.detail), errors, localize, recovery_url)
        if markup is None:
            return None
        return HTMLResponse(markup, status_code=error.status_code, headers=NO_STORE_HEADERS)
    except ApplicationError:
        # Deleted parent/item: never build a recovery page for another project.
        return None
