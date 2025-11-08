from typing import Optional, Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Mode
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.mode import ModePublicSchema, ModeCreateSchema, ModeUpdateSchema, ModePartialUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/modes/{mode_id}', response_model=ModePublicSchema)
async def get_mode(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_id: int,
):
    mode = Mode.get_or_none(Mode.id == mode_id)
    if mode is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Режим не найден.')
    return mode


@router.get('/modes', response_model=List[ModePublicSchema])
async def get_modes_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        name: Optional[str] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = Mode.select()
    if name:
        db_query = db_query.where(Mode.name == name)

    modes = db_query.limit(limit).offset(offset).order_by(Mode.id.asc())
    return modes


@router.post('/modes', response_model=ModePublicSchema)
async def create_mode(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_data: ModeCreateSchema,
):
    mode = Mode.create(**mode_data.model_dump())
    return mode


@router.put('/modes/{mode_id}', response_model=ModePublicSchema)
async def update_mode(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_id: int,
        mode_data: ModeUpdateSchema,
):
    """
    Обновляет режим по переданному ID.
    """
    mode = Mode.get_or_none(Mode.id == mode_id)
    if mode is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Режим не найден.')

    mode = update_endpoint_object(mode, mode_data, True)
    return mode


@router.patch('/modes/{mode_id}', response_model=ModePublicSchema)
async def partial_update_mode(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_id: int,
        mode_update: ModePartialUpdateSchema,
):
    mode = Mode.get_or_none(Mode.id == mode_id)
    if mode is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Режим не найден.')

    mode = update_endpoint_object(mode, mode_update, False)
    return mode
