"""
System-level API routes (Admin Only).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.middleware.rbac import RequireAdmin
from src.infra.tools.system_tools import open_program, scan_system_applications, terminate_program


router = APIRouter()


class AppRequest(BaseModel):
    app_name: str


@router.post("/system/scan", dependencies=[Depends(RequireAdmin)])
async def trigger_system_scan() -> dict[str, str]:
    """Forces an app cache rebuild (Requires Admin)."""
    result = scan_system_applications()
    return {"status": "success", "result": result}


@router.post("/system/open", dependencies=[Depends(RequireAdmin)])
async def trigger_open_app(request: AppRequest) -> dict[str, str]:
    """Opens a system app (Requires Admin)."""
    result = open_program(app_name=request.app_name)
    return {"status": "success", "result": result}


@router.post("/system/terminate", dependencies=[Depends(RequireAdmin)])
async def trigger_terminate_app(request: AppRequest) -> dict[str, str]:
    """Terminates a system app (Requires Admin)."""
    result = terminate_program(app_name=request.app_name)
    return {"status": "success", "result": result}
