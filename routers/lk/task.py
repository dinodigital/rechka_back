from functools import reduce
from operator import or_
from typing import Optional, Annotated, Dict

import peewee
from fastapi import APIRouter, Depends, HTTPException, Query
from peewee import fn
from starlette.status import HTTP_404_NOT_FOUND

from data.models import Report, Task, TableViewSettings, TableActiveFilter, ModeAnswer, ModeQuestion, ColumnFilter
from modules.assembly import Assembly
from modules.report_generator import ReportGenerator
from routers.auth import get_current_active_user
from schemas.task import TaskPublicSchema, TaskUpdateSchema, TranscriptPublicSchema
from routers.helpers import update_endpoint_object
from schemas.user import UserModel


router = APIRouter()


@router.get('/tasks/{task_id}', response_model=TaskPublicSchema)
async def get_task(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        task_id: int,
):
    task = Task.get_or_none(Task.id == task_id)
    if task is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Задача не найдена.')
    return task


@router.get('/tasks/{task_id}/transcript', response_model=TranscriptPublicSchema)
async def get_task_transcript(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        task_id: int,
):
    """
    Возвращает транскрипт разговора для указанной задачи.
    """
    task = Task.get_or_none(Task.id == task_id)
    if task is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Задача не найдена.')

    if task.transcript_id is None:
        transcript_text = None
    else:
        transcript = Assembly('').get_transcript_by_id(task.transcript_id)
        report_generator = ReportGenerator(transcript=transcript)
        transcript_text = report_generator.generate_transcript()

    return TranscriptPublicSchema(
        task_id=task_id,
        transcript=transcript_text,
    )


def filter_tasks(
        table_settings: TableViewSettings,
        task_ids: peewee.ModelSelect,
) -> Optional[peewee.ModelSelect]:
    """
    Фильтрует задачи по фильтрам вида просмотра.
    """
    # Активные вопросы отчета.
    mode_questions = ModeQuestion.select().where(ModeQuestion.report == table_settings.report,
                                                 ModeQuestion.is_active == True)

    # Активные фильтры указанного вида для указанного отчета.
    table_filters = TableActiveFilter.select().where(TableActiveFilter.table_settings == table_settings,
                                                     TableActiveFilter.mode_question.in_(mode_questions))

    # Если ни одного фильтра не указано, то возвращаем исходный список задач.
    if not table_filters.exists():
        return None

    # Предварительная обработка фильтров
    filter_conditions = []
    for table_filter in table_filters:
        expr = ColumnFilter.build(
            ModeAnswer.answer_text,
            table_filter.mode_question.answer_type,
            table_filter.operation,
            table_filter.value
        )
        filter_conditions.append({'question': table_filter.mode_question, 'expr': expr})

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


@router.get('/tasks', response_model=Dict)
async def get_tasks_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        status: Optional[str] = Task.StatusChoices.DONE,
        is_archived: Optional[bool] = None,
        source: Optional[str] = None,
        report_id: Optional[int] = Query(None),
        table_settings_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=500),
        offset: int = Query(0, ge=0),
):
    """
    table_settings_id можно передать только вместе с report_id.
    """
    db_query = Task.select()

    if status is not None:
        db_query = db_query.where(Task.status == status)
    if is_archived is not None:
        db_query = db_query.where(Task.is_archived == is_archived)

    # Фильтр по источнику задачи (main, dashboard).
    if source is not None:
        if source == 'main':
            db_query = db_query.where(or_(Task.source == source, Task.source.is_null(True)))
        else:
            db_query = db_query.where(Task.source == source)

    # Если указан ID отчета, то оставляем только задачи отчета.
    if report_id is not None:
        report = Report.get_or_none(Report.id == report_id)
        if report is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')
        db_query = db_query.where(Task.report == report)

        # Если для отчета нужно отфильтровать задачи еще и по фильтрам «Вида».
        if table_settings_id is not None:
            table_settings = TableViewSettings.get_or_none(TableViewSettings.id == table_settings_id)
            if table_settings is None:
                raise HTTPException(HTTP_404_NOT_FOUND, detail='Вид просмотра таблицы не найден.')

            filtered_task_ids = filter_tasks(table_settings, db_query.select(Task.id))
            if filtered_task_ids is not None:
                db_query = db_query.where(Task.id.in_(filtered_task_ids))

    total_count = db_query.count()
    tasks = db_query.limit(limit).offset(offset).order_by(Task.id.desc())
    page_count = tasks.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [TaskPublicSchema.model_validate(x) for x in tasks],
    }
    return response


@router.patch('/tasks/{task_id}', response_model=TaskPublicSchema)
async def partial_update_task(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        task_id: int,
        task_update: TaskUpdateSchema,
):
    task = Task.get_or_none(Task.id == task_id)
    if task is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Задача не найдена.')

    task = update_endpoint_object(task, task_update, False)
    return task
