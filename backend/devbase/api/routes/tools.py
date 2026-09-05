from fastapi import APIRouter, Depends

from devbase.api.dependencies import get_runtime, require_local_token
from devbase.api.schemas import (
    ToolListResponse,
    tool_descriptor_response,
)
from devbase.application.job_runtime import JobRuntime

router = APIRouter(
    prefix="/tools",
    tags=["tools"],
    dependencies=[Depends(require_local_token)],
)


@router.get("", response_model=ToolListResponse)
def list_tools(runtime: JobRuntime = Depends(get_runtime)) -> ToolListResponse:
    """Return all registered tool descriptors for the frontend nav layer."""
    return ToolListResponse(
        tools=[tool_descriptor_response(d) for d in runtime.registry().descriptors()]
    )
