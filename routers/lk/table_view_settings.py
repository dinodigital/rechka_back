from typing import Annotated, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from data.models import main_db, TableViewSettings, User, Report, Company, ColumnDisplay, TableActiveFilter
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from routers.lk.integration import get_accessible_integration
from schemas.table_view_settings import TableViewSettingsPublicSchema, TableViewSettingsCreateSchema, \
    TableViewSettingsUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/table_settings/{obj_id}', response_model=TableViewSettingsPublicSchema)
async def get_table_view_settings(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    obj = TableViewSettings.get_or_none(TableViewSettings.id == obj_id)
    if obj is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    # Проверка доступа.
    if (
            not current_user.is_admin
            and
            not (current_user.company_id == obj.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    return obj


@router.get('/table_settings', response_model=Dict)
async def get_table_view_settings_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = TableViewSettings.select()

    # Интеграции, доступные пользователю для чтения.
    allowed_integrations = get_accessible_integration(current_user.id, allow_company_user=True)
    # Отчеты, доступные пользователю для чтения.
    allowed_reports = Report.select().where(Report.integration.in_(allowed_integrations))

    # Фильтр по отчету.
    if report_id is not None:
        allowed_reports = allowed_reports.where(Report.id == report_id)
        if not allowed_reports.exists():
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    db_query = db_query.where(TableViewSettings.report.in_(allowed_reports))

    total_count = db_query.count()
    items = db_query.limit(limit).offset(offset).order_by(TableViewSettings.id.asc())
    page_count = items.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [TableViewSettingsPublicSchema.model_validate(x) for x in items],
    }
    return response


@router.post('/table_settings', response_model=TableViewSettingsPublicSchema)
async def create_table_view_settings(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: TableViewSettingsCreateSchema,
):
    user = User.get(User.id == current_user.id)

    # Интеграции, доступные пользователю для чтения.
    allowed_integrations = get_accessible_integration(current_user.id, allow_company_user=True)
    # Отчеты, доступные пользователю для чтения.
    allowed_reports = Report.select().where(Report.integration.in_(allowed_integrations))
    report = allowed_reports.where(Report.id == data.report_id).first()
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    table_settings = TableViewSettings.create(user=user,
                                              report=report,
                                              name=data.name)

    return table_settings


@router.put('/table_settings/{obj_id}', response_model=TableViewSettingsPublicSchema)
async def update_table_view_settings(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: TableViewSettingsUpdateSchema,
):
    obj = TableViewSettings.get_or_none(TableViewSettings.id == obj_id)
    if obj is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    # Проверка доступа.
    if (
            not current_user.is_admin
            and
            not (current_user.company_id == obj.get_company_id() and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == obj.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    obj = update_endpoint_object(obj, data, True)

    return obj


@router.delete('/table_settings/{obj_id}', response_model=Dict)
async def delete_table_view_settings(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    table_settings = TableViewSettings.get_or_none(TableViewSettings.id == obj_id)
    if table_settings is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    # Проверка доступа.
    if (
            not current_user.is_admin
            and
            not (current_user.company_id == table_settings.get_company_id()
                 and current_user.company_role == Company.Roles.ADMIN)
            and
            not (current_user.id == table_settings.user.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

    # Удаляем вид и все связанные с ним объекты.
    response = {}
    with main_db.atomic():
        deleted_column_displays = ColumnDisplay.delete().where(ColumnDisplay.table_settings == table_settings).execute()
        response['column_displays'] = deleted_column_displays
        deleted_active_filters = TableActiveFilter.delete().where(TableActiveFilter.table_settings == table_settings).execute()
        response['active_filters'] = deleted_active_filters
        table_settings.delete_instance()
        response['table_settings'] = 1

    return response
