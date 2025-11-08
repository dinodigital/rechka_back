from typing import Annotated, List
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Chart, ChartFilter, ModeQuestion
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.chart_filter import ChartFilterPublicSchema, ChartFilterCreateSchema, \
    ChartFilterUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/charts/{obj_id}/filters', response_model=List[ChartFilterPublicSchema])
async def get_chart_filters_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    chart = Chart.get_or_none(Chart.id == obj_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    chart_filters = ChartFilter.select().where(ChartFilter.chart == chart)
    return chart_filters


@router.post('/charts/{obj_id}/filters', response_model=ChartFilterPublicSchema)
async def create_chart_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: ChartFilterCreateSchema,
):
    chart = Chart.get_or_none(Chart.id == obj_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == data.mode_question_id,
                                             ModeQuestion.report == chart.report)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    chart_filter = ChartFilter.create(
        chart=chart,
        mode_question=mode_question,
        operation=data.operation,
        value=data.value,
    )
    return chart_filter


@router.put('/charts/{chart_id}/filters/{filter_id}', response_model=ChartFilterPublicSchema)
async def update_chart_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        filter_id: int,
        data: ChartFilterUpdateSchema,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    chart_filter = ChartFilter.get_or_none(ChartFilter.id == filter_id,
                                           ChartFilter.chart == chart)
    # Проверка доступа.
    if chart_filter is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Фильтр не найден.')

    chart_filter = update_endpoint_object(chart_filter, data, True)
    return chart_filter


@router.delete('/charts/{chart_id}/filters/{filter_id}', response_model=Dict)
async def delete_chart_filter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        filter_id: int,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.get_company_id())
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    chart_filter = ChartFilter.get_or_none(ChartFilter.id == filter_id,
                                           ChartFilter.chart == chart)
    # Проверка доступа.
    if chart_filter is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Фильтр не найден.')

    chart_filter.delete_instance()
    response = {'chart_filter': 1}
    return response
