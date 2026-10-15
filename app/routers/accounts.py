"""Account form and explicitly authorized secret-reveal HTTP adapters."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..presentation import redirect_to_project
from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..services import accounts

from ..submissions import MutationRoute

router = APIRouter(route_class=MutationRoute)


@router.post("/projects/{project_id}/accounts")
def add_access_account(
    request: Request,
    project_id: int,
    label: str = Form(...),
    category: str = Form("website"),
    environment: str = Form("test"),
    endpoint: str = Form(""),
    database_name: str = Form(""),
    username: str = Form(""),
    role_scope: str = Form(""),
    purpose: str = Form(""),
    owner: str = Form(""),
    secret_reference: str = Form(""),
    secret_value: str = Form(""),
) -> RedirectResponse:
    project_id = accounts.add_access_account(
        runtime=get_runtime(request),
        token=request.cookies.get(VAULT_COOKIE_NAME),
        project_id=project_id,
        label=label,
        category=category,
        environment=environment,
        endpoint=endpoint,
        database_name=database_name,
        username=username,
        role_scope=role_scope,
        purpose=purpose,
        owner=owner,
        secret_reference=secret_reference,
        secret_value=secret_value,
    )
    return redirect_to_project(project_id)


@router.post("/accounts/{account_id}/edit")
def update_access_account(
    request: Request,
    account_id: int,
    label: str = Form(...),
    category: str = Form("website"),
    environment: str = Form("test"),
    endpoint: str = Form(""),
    database_name: str = Form(""),
    username: str = Form(""),
    role_scope: str = Form(""),
    purpose: str = Form(""),
    owner: str = Form(""),
    secret_reference: str = Form(""),
    secret_value: str = Form(""),
    delete_secret: bool = Form(False),
) -> RedirectResponse:
    project_id = accounts.update_access_account(
        runtime=get_runtime(request),
        token=request.cookies.get(VAULT_COOKIE_NAME),
        account_id=account_id,
        label=label,
        category=category,
        environment=environment,
        endpoint=endpoint,
        database_name=database_name,
        username=username,
        role_scope=role_scope,
        purpose=purpose,
        owner=owner,
        secret_reference=secret_reference,
        secret_value=secret_value,
        delete_secret=delete_secret,
    )
    return redirect_to_project(project_id)


@router.post("/accounts/{account_id}/delete")
def delete_access_account(account_id: int) -> RedirectResponse:
    project_id = accounts.delete_access_account(account_id=account_id)
    return redirect_to_project(project_id)


@router.post("/accounts/{account_id}/reveal")
def reveal_access_account_secret(request: Request, account_id: int) -> JSONResponse:
    value = accounts.reveal_secret(
        get_runtime(request),
        request.cookies.get(VAULT_COOKIE_NAME),
        account_id,
    )
    return JSONResponse({"secret": value}, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, private",
        "Pragma": "no-cache", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    })
