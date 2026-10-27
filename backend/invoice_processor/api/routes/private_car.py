"""私车公用登记 API（v7.6.0）：元信息/登记行/导出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...application.private_car_service import PrivateCarService
from ..dependencies import require_local_token
from ..schemas import (
    PrivateCarExportRequest,
    PrivateCarExportResponse,
    PrivateCarMeta,
    PrivateCarMetaPatch,
    PrivateCarRowsPayload,
    PrivateCarRowsResponse,
)

router = APIRouter(
    prefix='/private-car',
    tags=['private-car'],
    dependencies=[Depends(require_local_token)],
)


def get_private_car_service(request: Request) -> PrivateCarService:
    return request.app.state.private_car_service


@router.get('/meta', response_model=PrivateCarMeta)
def get_private_car_meta(
    service: PrivateCarService = Depends(get_private_car_service),
) -> PrivateCarMeta:
    return PrivateCarMeta(**service.get_meta())


@router.patch('/meta', response_model=PrivateCarMeta)
def patch_private_car_meta(
    request: PrivateCarMetaPatch,
    service: PrivateCarService = Depends(get_private_car_service),
) -> PrivateCarMeta:
    values = request.model_dump(exclude_unset=True)
    return PrivateCarMeta(**service.set_meta(**values))


@router.get('/rows', response_model=PrivateCarRowsResponse)
def get_private_car_rows(
    service: PrivateCarService = Depends(get_private_car_service),
) -> PrivateCarRowsResponse:
    return PrivateCarRowsResponse(rows=service.get_rows())


@router.put('/rows', response_model=PrivateCarRowsResponse)
def put_private_car_rows(
    payload: PrivateCarRowsPayload,
    service: PrivateCarService = Depends(get_private_car_service),
) -> PrivateCarRowsResponse:
    """整体替换登记行（前端整表提交，与同事版表格口径一致）。"""
    rows = service.replace_rows(
        [row.model_dump() for row in payload.rows]
    )
    return PrivateCarRowsResponse(rows=rows)


@router.post('/export', response_model=PrivateCarExportResponse)
def export_private_car(
    request: PrivateCarExportRequest,
    service: PrivateCarService = Depends(get_private_car_service),
) -> PrivateCarExportResponse:
    path = service.export(
        rows=(
            [row.model_dump() for row in request.rows]
            if request.rows is not None
            else None
        ),
        license_plate=request.license_plate,
        source_directory=request.source_directory,
        output_directory=request.output_directory,
    )
    return PrivateCarExportResponse(path=path)
