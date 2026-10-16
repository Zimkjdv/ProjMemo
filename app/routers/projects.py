"""Project HTTP views and forms; project services own queries and mutations."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..presentation import page_context, redirect_to_project, templates
from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..services import lifecycle, projects, vault
from ..services.workspace import load_workspace

from ..submissions import MutationRoute

router = APIRouter(route_class=MutationRoute)


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = '',
    status: str = '',
    view: str = 'cards',
    page_size: int = 10,
    page: int = 1,
) -> HTMLResponse:
    values = projects.list_projects(q=q, status=status, view=view, page_size=page_size, page=page,
                                   collection=request.query_params.get("collection", "active"),
                                   **{key: request.query_params.get(key, "")
                                      for key in ("owner", "tag", "search_scope", "handover")})
    return templates.TemplateResponse(request, "index.html", page_context(request, **values))


@router.get("/projects/new", response_class=HTMLResponse)
def new_project(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "project_form.html",
        page_context(request, project=None, form_title="建立專案"),
    )


@router.post("/projects/new")
def create_project(
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("maintenance"),
    owner: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    project_id = projects.create_project(
        name=name,
        description=description,
        status=status,
        owner=owner,
        tags=tags,
    )
    return redirect_to_project(project_id)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def show_project(request: Request, project_id: int) -> HTMLResponse:
    fragment = request.headers.get("X-ProjMemo-Fragment") == "notes" and request.method == "GET"
    values = load_workspace(project_id,
        page=getattr(request.state, "notes_page", request.query_params.get("notes_page", "1")),
        size=getattr(request.state, "notes_size", request.query_params.get("notes_size", "20")),
        edit_note_id=getattr(request.state, "editing_note_id", None), notes_only=fragment,
        checklist_filter=getattr(request.state, "checklist_filter", request.query_params.get("checklist", "")))
    if fragment:
        return templates.TemplateResponse(request, "_project_notes.html", page_context(request, **values),
            headers={"X-ProjMemo-Fragment": "notes", "Cache-Control": "no-store", "Vary": "X-ProjMemo-Fragment, Cookie"})
    session_status = vault.vault_status_context(
        get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME),
        values["vault_configured"], values["allow_secret_export"],
    )
    values.update(vault_unlocked=session_status["unlocked"], vault_session_status=session_status)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        page_context(request, **values),
        headers={"Cache-Control": "no-store", "Vary": "X-ProjMemo-Fragment, Cookie"},
    )


@router.get("/projects/{project_id}/edit", response_class=HTMLResponse)
def edit_project(request: Request, project_id: int) -> HTMLResponse:
    project = projects.load_project(project_id)
    return templates.TemplateResponse(
        request,
        "project_form.html",
        page_context(request, project=project, form_title="編輯專案"),
    )


@router.post("/projects/{project_id}/edit")
def update_project(
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    status: str = Form("maintenance"),
    owner: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    project_id = projects.update_project(
        project_id=project_id,
        name=name,
        description=description,
        status=status,
        owner=owner,
        tags=tags,
    )
    return redirect_to_project(project_id)


@router.get("/projects/{project_id}/manage", response_class=HTMLResponse)
def manage_project(request: Request, project_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "project_manage.html", page_context(request, **lifecycle.management_data(project_id)),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/projects/{project_id}/lifecycle/{action}")
def change_lifecycle(
    request: Request, project_id: int, action: str,
    revision: int = Form(..., ge=0), confirmation_name: str = Form(""), confirmed: bool = Form(False),
) -> RedirectResponse:
    destination = lifecycle.transition(project_id=project_id, action=action, revision=revision,
        confirmation_name=confirmation_name, confirmed=confirmed, runtime=get_runtime(request))
    return RedirectResponse(destination, 303, headers={"Cache-Control": "no-store"})
