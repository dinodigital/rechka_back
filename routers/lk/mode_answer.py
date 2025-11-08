from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from data.models import ModeAnswer, Task, ModeQuestion
from routers.auth import get_current_active_user
from schemas.mode_answer import ModeAnswerPublicSchema, ModeAnswerCreateSchema
from schemas.user import UserModel

router = APIRouter()


@router.get('/mode_answers/{mode_answer_id}', response_model=ModeAnswerPublicSchema)
async def get_mode_answer(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    obj = ModeAnswer.get_or_none(ModeAnswer.id == obj_id)
    if obj is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Ответ не найден.')
    return obj


@router.get('/mode_answers', response_model=Dict)
async def get_mode_answers_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        task_ids: str = None,
        limit: int = Query(10, ge=1, le=500),
        offset: int = Query(0, ge=0),
):
    db_query = ModeAnswer.select()

    if task_ids is not None:
        task_ids = [x.strip() for x in task_ids.split(',')]
        if not task_ids:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Передан пустой список задач.')
        db_query = db_query.where(ModeAnswer.task.in_(task_ids))

    total_count = db_query.count()
    mode_answers = (
        db_query
        .limit(limit)
        .offset(offset)
        .order_by(ModeAnswer.id.asc())
    )
    page_count = mode_answers.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ModeAnswerPublicSchema.model_validate(x) for x in mode_answers],
    }
    return response


@router.post('/mode_answers', response_model=ModeAnswerPublicSchema)
async def create_mode_answer(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ModeAnswerCreateSchema,
):
    task = Task.get_or_none(Task.id == data.task_id)
    if task is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Задача не найдена.')

    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == data.question_id,
                                             ModeQuestion.report == task.report)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    mode_answer = ModeAnswer.create(
        task=task,
        question=mode_question,
        answer_text=data.answer_text,
    )
    return mode_answer
