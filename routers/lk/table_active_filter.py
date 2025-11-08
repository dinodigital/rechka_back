from typing import Annotated, List
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_404_NOT_FOUND

from data.models import ColumnFilter, Company
from data.models import TableViewSettings, ModeQuestion, TableActiveFilter
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.table_active_filter import TableActiveFilterPublicSchema, TableActiveFilterCreateSchema, \
    TableActiveFilterUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/filter_operations', response_model=Dict)
async def get_possible_filter_operations(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    response = {
        'result': ColumnFilter.FILTER_OPERATIONS,
    }
    return response


@router.get('/table_settings/{obj_id}/filters', response_model=List[TableActiveFilterPublicSchema])
async def get_table_filters_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    table_settings = TableViewSettings.get_or_none(TableViewSettings.id == obj_id)

    # Проверка доступа.
    if table_settings is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == table_settings.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    filters = TableActiveFilter.select().where(TableActiveFilter.table_settings == table_settings)
    return filters


@router.post('/table_settings/{obj_id}/filters', response_model=TableActiveFilterPublicSchema)
async def create_table_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: TableActiveFilterCreateSchema,
):
    table_settings = TableViewSettings.get_or_none(TableViewSettings.id == obj_id)

    # Проверка доступа.
    if table_settings is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == table_settings.get_company_id() and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == data.mode_question_id,
                                             ModeQuestion.report == table_settings.report)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    table_filter = TableActiveFilter.create(
        table_settings=table_settings,
        mode_question=mode_question,
        operation=data.operation,
        value=data.value,
    )
    return table_filter


@router.put('/filters/{obj_id}', response_model=TableActiveFilterPublicSchema)
async def update_table_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: TableActiveFilterUpdateSchema,
):
    table_filter = TableActiveFilter.get_or_none(TableActiveFilter.id == obj_id)

    # Проверка доступа.
    if table_filter is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == table_filter.table_settings.get_company_id() and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == table_filter.table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Фильтр не найден.')

    table_filter = update_endpoint_object(table_filter, data, True)
    return table_filter


@router.delete('/filters/{obj_id}', response_model=Dict)
async def delete_table_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    table_filter = TableActiveFilter.get_or_none(TableActiveFilter.id == obj_id)

    # Проверка доступа.
    if table_filter is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == table_filter.table_settings.get_company_id() and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == table_filter.table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Фильтр не найден.')

    table_filter.delete_instance()
    response = {'table_filter': 1}
    return response
