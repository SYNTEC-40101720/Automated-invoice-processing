"""DevBase 工具清单路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from devbase.application.job_runtime import JobRuntime

from ..dependencies import get_devbase_runtime, require_local_token
from ..schemas import ToolDescriptorResponse, ToolListResponse


router = APIRouter(
    prefix='/tools',
    tags=['tools'],
    dependencies=[Depends(require_local_token)],
)


@router.get('', response_model=ToolListResponse)
def list_tools(
    runtime: JobRuntime = Depends(get_devbase_runtime),
) -> ToolListResponse:
    return ToolListResponse(
        tools=[
            ToolDescriptorResponse(
                kind=descriptor.kind,
                title=descriptor.title,
                subtitle=descriptor.subtitle,
                group=descriptor.group,
                glyph=descriptor.glyph,
                access_key=descriptor.access_key,
                supports_input=descriptor.supports_input,
                mode=descriptor.mode,
            )
            for descriptor in runtime.registry().descriptors()
        ]
    )