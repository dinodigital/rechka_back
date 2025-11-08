from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND, HTTP_400_BAD_REQUEST

from data.models import Chart
from data.models import ChartParameter, ModeQuestion
from routers.auth import get_current_active_user
from schemas.chart_parameter import ChartParameterPublicSchema, \
    ChartParameterCreateSchema, ChartParameterPartialUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/charts/{chart_id}/parameters/{parameter_id}', response_model=ChartParameterPublicSchema)
async def get_chart_parameter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        parameter_id: int,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    parameter = ChartParameter.get_or_none(id=parameter_id, chart=chart)
    if parameter is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Параметр графика не найден.')

    return parameter



@router.get('/charts/{chart_id}/parameters', response_model=Dict)
async def get_chart_parameters_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    db_query = ChartParameter.select().where(ChartParameter.chart == chart)

    total_count = db_query.count()
    items = db_query.limit(limit).offset(offset).order_by(ChartParameter.id.asc())
    page_count = items.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ChartParameterPublicSchema.model_validate(x) for x in items],
    }
    return response



@router.post('/charts/{chart_id}/parameters', response_model=ChartParameterPublicSchema)
async def create_chart_parameter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        data: ChartParameterCreateSchema,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    mode_question = ModeQuestion.get_or_none(id=data.mode_question_id,
                                             report=chart.report)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    if (ChartParameter.select().where(ChartParameter.chart == chart,
                                      ChartParameter.data_type != data.data_type).exists()):
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Некорректный тип параметра графика.')

    parameter = ChartParameter.create(
        chart=chart,
        mode_question=mode_question,
        color=data.color,
        data_type=data.data_type,
        metric_operation=data.metric_operation,
        metric_condition=data.metric_condition,
        is_hidden=data.is_hidden,
    )
    return parameter


@router.patch('/charts/{chart_id}/parameters/{parameter_id}', response_model=ChartParameterPublicSchema)
async def partial_update_chart_parameter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        parameter_id: int,
        data: ChartParameterPartialUpdateSchema,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    parameter = ChartParameter.get_or_none(id=parameter_id, chart=chart)
    if parameter is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Параметр графика не найден.')

    # Новый вопрос параметра графика. Должен принадлежать тому же отчету, что и график.
    if data.mode_question_id is not None:
        new_mode_question = ModeQuestion.get_or_none(id=data.mode_question_id, report=chart.report)
        if new_mode_question is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')
    else:
        new_mode_question = None

    # Обновляем параметр графика.
    if new_mode_question is not None:
        parameter.mode_question = new_mode_question

    for field_name in ['color', 'data_type', 'metric_operation', 'metric_condition', 'is_hidden']:
        new_value = getattr(data, field_name)
        if new_value is not None:
            setattr(parameter, field_name, new_value)

    if parameter.is_dirty():
        parameter.save()

    return parameter


@router.delete('/charts/{chart_id}/parameters/{parameter_id}', response_model=Dict)
async def delete_chart_parameter(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        parameter_id: int,
):
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    parameter = ChartParameter.get_or_none(id=parameter_id, chart=chart)
    if parameter is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Параметр графика не найден.')

    parameter.delete_instance()
    response = {'chart_parameter': 1}
    return response
