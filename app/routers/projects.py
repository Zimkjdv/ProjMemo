"""Project HTTP views and forms; project services own queries and mutations."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..presentation import page_context, redirect_to_project, templates
from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..services import projects, vault

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = '',
    status: str = '',
    view: str = 'cards',
    page_size: int = 10,
    page: int = 1,
) -> HTMLResponse:
    values = projects.list_projects(q=q, status=status, view=view, page_size=page_size, page=page)
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
    values = projects.load_project_page(project_id)
    session_status = vault.vault_status_context(
        get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME),
        values["vault_configured"], values["allow_secret_export"],
    )
    values.update(vault_unlocked=session_status["unlocked"], vault_session_status=session_status)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        page_context(request, **values),
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
