from typing import Annotated, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from data.models import TableViewSettings, ColumnDisplay, ModeQuestion, Company
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.column_display import ColumnDisplayPublicSchema, ColumnDisplayCreateSchema, ColumnDisplayUpdateSchema
from schemas.user import UserModel

router = APIRouter()


@router.get('/column_displays/{obj_id}', response_model=ColumnDisplayPublicSchema)
async def get_column_display(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    obj = ColumnDisplay.get_or_none(ColumnDisplay.id == obj_id)
    if obj is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отображение колонки не найдено.')

    # Проверка доступа.
    if (
            not current_user.is_admin
            and
            not (current_user.company_id == obj.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отображение колонки не найдено.')

    return obj


@router.get('/column_displays', response_model=Dict)
async def get_column_displays_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        table_settings_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = ColumnDisplay.select()

    # «Отображаемые колонки» по всем «Видам» доступны только системному администратору.
    if table_settings_id is None and not current_user.is_admin:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    # Фильтр по «Виду просмотра таблицы».
    if table_settings_id is not None:
        table_settings = TableViewSettings.get_or_none(TableViewSettings.id == table_settings_id)

        # Проверка доступа.
        if table_settings is None or (
                not current_user.is_admin
                and
                not (current_user.company_id == table_settings.get_company_id())
        ):
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

        db_query = db_query.where(ColumnDisplay.table_settings == table_settings)

    total_count = db_query.count()
    items = db_query.limit(limit).offset(offset).order_by(ColumnDisplay.id.asc())
    page_count = items.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ColumnDisplayPublicSchema.model_validate(x) for x in items],
    }
    return response


@router.post('/column_displays', response_model=ColumnDisplayPublicSchema)
async def create_column_display(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ColumnDisplayCreateSchema,
):
    table_settings = TableViewSettings.get_or_none(TableViewSettings.id == data.table_settings_id)

    # Проверка доступа. Изменять вид могут:
    # 1. Системный администратор.
    # 2. Администратор компании отчета.
    # 3. Создатель «Вида просмотра».
    if table_settings is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == table_settings.get_company_id()
                 and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == data.mode_question_id,
                                             ModeQuestion.report == table_settings.report)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    column = ColumnDisplay.create(table_settings=table_settings,
                                  mode_question=mode_question,
                                  is_on=data.is_on)
    return column


@router.put('/column_displays/{obj_id}', response_model=ColumnDisplayPublicSchema)
async def update_column_display(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: ColumnDisplayUpdateSchema,
):
    obj = ColumnDisplay.get_or_none(ColumnDisplay.id == obj_id)

    # Проверка доступа.
    if obj is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == obj.get_company_id()
                 and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == obj.table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отображение колонки не найдено.')

    obj = update_endpoint_object(obj, data, True)

    return obj
