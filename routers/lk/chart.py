import json
from collections import defaultdict
from datetime import date, timedelta
from functools import reduce
from typing import Annotated, Dict, Optional, List

import peewee
from fastapi import APIRouter, Depends, HTTPException, Query
from peewee import fn
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Chart, Report, Integration, MetricsOptions, Task, ModeAnswer, ChartMetricType, ChartParameter, \
    ModeQuestion, ChartFilter, ColumnFilter
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from routers.lk.integration import get_accessible_integration
from schemas.chart import ChartPublicSchema, ChartCreateSchema, ChartPartialUpdateSchema
from schemas.chart_parameter import ChartParameterDataPublicSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/charts/{obj_id}', response_model=ChartPublicSchema)
async def get_chart(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    chart = Chart.get_or_none(Chart.id == obj_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    return chart


@router.get('/charts', response_model=Dict)
async def get_charts_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_ids: Optional[str] = None,
        company_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = Chart.select()

    # Интеграции, доступные пользователю для чтения.
    allowed_integrations = get_accessible_integration(current_user.id, allow_company_user=True)

    # Фильтр по компании.
    if company_id is not None:
        allowed_integrations = allowed_integrations.where(Integration.company == company_id)
        if not allowed_integrations.exists():
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Графики не найдены.')

    # Отчеты, доступные пользователю для чтения.
    allowed_reports = Report.select().where(Report.integration.in_(allowed_integrations))

    # Фильтр по списку отчетов.
    if report_ids is not None:
        report_ids = [x.strip() for x in report_ids.split(',')]
        if not report_ids:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Передан пустой список отчетов.')
        allowed_reports = allowed_reports.where(Report.id.in_(report_ids))

    db_query = db_query.where(Chart.report.in_(allowed_reports))

    total_count = db_query.count()
    items = db_query.limit(limit).offset(offset).order_by(Chart.id.asc())
    page_count = items.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ChartPublicSchema.model_validate(x) for x in items],
    }
    return response


@router.post('/charts', response_model=ChartPublicSchema)
async def create_chart(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ChartCreateSchema,
):
    report = Report.get_or_none(Report.id == data.report_id)

    # Проверка доступа.
    if report is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    chart = Chart.create(report=report,
                         name=data.name,
                         order=data.order)
    return chart


@router.patch('/charts/{obj_id}', response_model=ChartPublicSchema)
async def partial_update_chart(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
        data: ChartPartialUpdateSchema,
):
    chart = Chart.get_or_none(Chart.id == obj_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    chart = update_endpoint_object(chart, data, False)
    return chart


@router.delete('/charts/{obj_id}', response_model=Dict)
async def delete_chart(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    chart = Chart.get_or_none(Chart.id == obj_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    chart.delete_instance()
    response = {'chart': 1}
    return response


@router.get('/charts_options', response_model=Dict)
async def get_possible_metrics_options(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    response = {
        'result': {
            'metrics_options': MetricsOptions,
        }
    }
    return response



def get_percent_answer_value(answer_text: str) -> int:
    try:
        return int(answer_text.replace('%', '').strip())
    except ValueError:
        return 0


def calculate_parameter_value(
        parameter: ChartParameter,
        answer_texts: List[str],
):
    """
    Вычисляет значение параметра на графике.
    """

    # Операция одинаковая для всех типов параметров.
    if parameter.metric_operation == 'count':
        value = len(answer_texts)

    else:
        if parameter.data_type in {ChartMetricType.INTEGER, ChartMetricType.PERCENT}:
            values_list = [get_percent_answer_value(x) for x in answer_texts]

            if parameter.metric_operation == 'max':
                value = max(values_list)
            elif parameter.metric_operation == 'min':
                value = min(values_list)
            elif parameter.metric_operation == 'average':
                value = round(1.0 * sum(values_list) / len(values_list), 2)
            else:
                if parameter.data_type == ChartMetricType.INTEGER and parameter.metric_operation == 'sum':
                    value = sum(values_list)
                else:
                    raise HTTPException(HTTP_404_NOT_FOUND, detail='Неизвестная операция над параметром графика.')

        elif parameter.data_type == ChartMetricType.MULTIPLE_CHOICE:
            if parameter.metric_operation == 'percentage_of_total':
                # Варианты ответов, по которым нужно фильтровать.
                condition_values = [x.lower() for x in json.loads(parameter.metric_condition)]
                filtered_values = [x for x in answer_texts if x.lower() in condition_values]
                # Общее число записей / Число записей, прошедших фильтр.
                value = round(1.0 * len(filtered_values) / len(answer_texts), 2)
            else:
                raise HTTPException(HTTP_404_NOT_FOUND, detail='Неизвестная операция над параметром графика.')

        else:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Неизвестная операция над параметром графика.')

    return value


def filter_chart_tasks(
        chart: Chart,
        task_ids,
) -> Optional[peewee.ModelSelect]:
    """
    Фильтрует задачи по фильтрам графика.
    """

    # Активные вопросы отчета графика.
    mode_questions = ModeQuestion.select().where(ModeQuestion.report == chart.report,
                                                 ModeQuestion.is_active == True)
    # Активные фильтры указанного вида для указанного отчета.
    chart_filters = ChartFilter.select().where(ChartFilter.chart == chart,
                                               ChartFilter.mode_question.in_(mode_questions))

    # Если ни одного фильтра не указано, то возвращаем исходный список задач.
    if not chart_filters.exists():
        return None

    # Предварительная обработка фильтров
    filter_conditions = []
    for chart_filter in chart_filters:
        expr = ColumnFilter.build(
            ModeAnswer.answer_text,
            chart_filter.mode_question.answer_type,
            chart_filter.operation,
            chart_filter.value
        )
        filter_conditions.append({'question': chart_filter.mode_question, 'expr': expr})

    total_expr = reduce(lambda acc, cond: acc | ((ModeAnswer.question == cond['question']) & cond['expr']),
                        filter_conditions,
                        False)

    filtered_task_ids = (
        Task
        .select(Task.id)
        .where(Task.id.in_(task_ids))
        .join(ModeAnswer)
        .where(total_expr)
        .group_by(Task.id)
        .having(fn.COUNT(Task.id) == len(filter_conditions))
    )
    return filtered_task_ids


def make_parameter_data(
        parameter: ChartParameter,
        task_ids: peewee.ModelSelect,
        from_date: date,
        to_date: date,
) -> List[dict]:
    """
    Формирует данные для параметра графика с разбивкой по шагам.
    """
    # Шаг графика определяется диапазоном дат, для которого нужно получить данные.
    # Если этот диапазон равен одному дню, то шагом является час, а иначе – день.
    group_by_hour = from_date == to_date

    # Ответы, связанные с данным параметром и нужными задачами.
    mode_answers = (
        ModeAnswer
        .select(
            ModeAnswer.answer_text,
            ModeAnswer.task,
        )
        .where(
            ModeAnswer.question == parameter.mode_question,
            ModeAnswer.task.in_(task_ids)
        )
        .order_by(ModeAnswer.id)
    )

    # Группируем данные по дням/часам.
    grouped_by_step = defaultdict(list)
    for ma in mode_answers:
        if group_by_hour:
            step_name = ma.task.created.time().hour
        else:
            step_name = ma.task.created.date()
        grouped_by_step[step_name].append(ma.answer_text)

    # Вычисляем координаты параметра для всех шагов.
    coordinates = {}
    for step_name, answer_texts in grouped_by_step.items():
        coordinates[step_name] = calculate_parameter_value(parameter, answer_texts)

    # Заполняем шаги, для которых не было задач.
    if group_by_hour:
        for hour in range(1, 25):
            if hour not in coordinates:
                coordinates[hour] = None
    else:
        temp_date = from_date
        while temp_date <= to_date:
            if temp_date not in coordinates:
                coordinates[temp_date] = None
            temp_date += timedelta(days=1)

    data = [{'date': k, 'value': v} for k, v in sorted(coordinates.items(), key=lambda x: x[0])]
    return data


@router.get('/charts/{chart_id}/data', response_model=Dict)
async def get_chart_data(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        chart_id: int,
        from_date: date,
        to_date: date,
):
    """
    Возвращает данные о графике для отрисовки:
    - параметры графика;
    - параметры выборки;
    - данные графика (координаты).
    """
    chart = Chart.get_or_none(Chart.id == chart_id)

    # Проверка доступа.
    if chart is None or (
            not current_user.is_admin
            and
            not (current_user.company_id == chart.report.integration.company.id)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='График не найден.')

    # Задачи за нужный период.
    task_ids = Task.select(Task.id).where(
        fn.DATE(Task.created) >= fn.DATE(from_date),
        fn.DATE(Task.created) <= fn.DATE(to_date),
        Task.report == chart.report,
    )
    # Фильтруем задачи.
    filtered_task_ids = filter_chart_tasks(chart, task_ids)
    if filtered_task_ids is not None:
        task_ids = filtered_task_ids

    parameters = ChartParameter.select().where(ChartParameter.chart == chart)

    parameters_validated = []
    for parameter in parameters:
        if parameter.is_hidden:
            data = None
        else:
            data = make_parameter_data(parameter, task_ids, from_date, to_date)
        parameters_validated.append(
            ChartParameterDataPublicSchema(
                id=parameter.id,
                chart_id=parameter.chart.id,
                mode_question_id=parameter.mode_question.id,
                color=parameter.color,
                data_type=parameter.data_type,
                metric_operation=parameter.metric_operation,
                metric_condition=parameter.metric_condition,
                is_hidden=parameter.is_hidden,
                data=data,
            )
        )

    response = {
        'chart': ChartPublicSchema.model_validate(chart),
        'parameters': parameters_validated,
        'from_date': from_date,
        'to_date': to_date,
    }
    return response
