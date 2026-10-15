"""Local operational probes, deliberately outside the business OpenAPI contract."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..operations import database_ready
from ..web_security import NO_STORE_HEADERS

router = APIRouter()


@router.get("/health/live", include_in_schema=False)
def live():
    return JSONResponse({"status": "alive"}, headers=NO_STORE_HEADERS)


@router.get("/health/ready", include_in_schema=False)
def ready(request: Request):
    available = request.app.state.startup_ready and database_ready()
    return JSONResponse({"status": "ready" if available else "not_ready"},
                        status_code=200 if available else 503, headers=NO_STORE_HEADERS)
