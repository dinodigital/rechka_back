from typing import Annotated, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from data.models import ModeQuestion, ModeQuestionCalcType, Report
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.mode_question import ModeQuestionPublicSchema, ModeQuestionCreateSchema, ModeQuestionUpdateSchema, \
    ModeQuestionPartialUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/mode_questions/{mode_question_id}', response_model=ModeQuestionPublicSchema)
async def get_mode_question(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        obj_id: int,
):
    obj = ModeQuestion.get_or_none(ModeQuestion.id == obj_id)
    if obj is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')
    return obj


@router.get('/mode_questions', response_model=Dict)
async def get_mode_questions_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_ids: Optional[str] = None,
        is_active: Optional[bool] = True,
        calc_type: Optional[ModeQuestionCalcType] = None,
        answer_types: str = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = ModeQuestion.select()

    # Фильтр по списку отчетов.
    if report_ids is not None:
        report_ids = [x.strip() for x in report_ids.split(',')]
        if not report_ids:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Передан пустой список отчетов.')
        db_query = db_query.where(ModeQuestion.report.in_(report_ids))

    if is_active is not None:
        db_query = db_query.where(ModeQuestion.is_active == is_active)

    if calc_type is not None:
        db_query = db_query.where(ModeQuestion.calc_type == calc_type)

    if answer_types is not None:
        answer_types_list = [x.strip() for x in answer_types.split(',')]
        db_query = db_query.where(ModeQuestion.answer_type.in_(answer_types_list))

    total_count = db_query.count()
    mode_questions = (
        db_query
        .limit(limit)
        .offset(offset)
        .order_by(ModeQuestion.column_index.asc())
    )
    page_count = mode_questions.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ModeQuestionPublicSchema.model_validate(x) for x in mode_questions],
    }
    return response


@router.post('/mode_questions', response_model=ModeQuestionPublicSchema)
async def create_mode_question(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ModeQuestionCreateSchema,
):
    report = Report.get_or_none(Report.id == data.report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    mode_question = ModeQuestion.create(
        is_active=data.is_active,
        report=report,
        short_name=data.short_name,
        calc_type=data.calc_type,
        column_index=data.column_index,
        data=data.data,
        context=data.context,
        question_text=data.question_text,
        answer_type=data.answer_type,
        answer_format=data.answer_format,
        answer_options=data.answer_options,
        variant_colors=data.variant_colors,
    )
    return mode_question


@router.put('/mode_questions/{mode_question_id}', response_model=ModeQuestionPublicSchema)
async def update_mode_question(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_question_id: int,
        data: ModeQuestionUpdateSchema,
):
    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == mode_question_id)
    if mode_question is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    if mode_question.calc_type == ModeQuestionCalcType.AI:
        mode_question = update_endpoint_object(mode_question, data, True)

    return mode_question


@router.patch('/mode_questions/{mode_question_id}', response_model=ModeQuestionPublicSchema)
async def partial_update_mode_question(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_question_id: int,
        data: ModeQuestionPartialUpdateSchema,
):
    mode_question = ModeQuestion.get_or_none(ModeQuestion.id == mode_question_id)
    if mode_question is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Вопрос не найден.')

    if mode_question.calc_type in ModeQuestionCalcType.CUSTOM:
        ignore_fields = [
            'is_active',
            'short_name',
            'context',
            'question_text',
            'answer_format',
            'answer_options',
            'variant_colors',
        ]
    elif mode_question.calc_type in ModeQuestionCalcType.CRM:
        ignore_fields = [
            'short_name',
            'context',
            'question_text',
            'answer_format',
            'answer_options',
            'variant_colors',
        ]
    else:
        ignore_fields = []

    mode_question = update_endpoint_object(mode_question, data, False, ignore_fields=ignore_fields)
    return mode_question
