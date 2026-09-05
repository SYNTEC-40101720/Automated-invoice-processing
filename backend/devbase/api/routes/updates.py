from fastapi import APIRouter, Depends, HTTPException, Request

from devbase.api.dependencies import require_local_token
from devbase.api.schemas import (
    UpdateCheckResponse,
    UpdateProgressResponse,
    update_progress_response,
)
from devbase.desktop.update_manager import UpdateManager

router = APIRouter(
    prefix="/updates",
    tags=["updates"],
    dependencies=[Depends(require_local_token)],
)


def _manager(request: Request) -> UpdateManager:
    return request.app.state.update_manager


@router.get("/check", response_model=UpdateCheckResponse)
def check_update(request: Request) -> UpdateCheckResponse:
    result = _manager(request).check()
    release = result.release
    return UpdateCheckResponse(
        current=str(result.current),
        latest=None if result.latest is None else str(result.latest),
        available=result.available,
        installable=result.installable,
        asset_name=None if release is None else release.asset.name,
        release_url=None if release is None else release.html_url,
        error=result.error,
    )


@router.post("/apply", response_model=UpdateProgressResponse)
def apply_update(request: Request) -> UpdateProgressResponse:
    manager = _manager(request)
    try:
        manager.stage()
    except (RuntimeError, OSError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return update_progress_response(manager.progress())


@router.get("/progress", response_model=UpdateProgressResponse)
def update_progress(request: Request) -> UpdateProgressResponse:
    return update_progress_response(_manager(request).progress())
