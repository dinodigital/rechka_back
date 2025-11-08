from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from data.models import ModeTemplate, ModeQuestion, ModeTemplateQuestion, main_db, Report, Company
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from schemas.mode_template import ModeTemplatePublicSchema, ModeTemplateCreateSchema, ModeTemplateUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/mode_templates/{mode_template_id}', response_model=ModeTemplatePublicSchema)
async def get_mode_template(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_template_id: int,
):
    mode_template = ModeTemplate.get_or_none(ModeTemplate.id == mode_template_id)
    if mode_template is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Шаблон отчета не найден.')
    return mode_template


@router.get('/mode_templates', response_model=Dict)
async def get_mode_template_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    db_query = ModeTemplate.select()

    total_count = db_query.count()
    mode_templates = db_query.limit(limit).offset(offset).order_by(ModeTemplate.id.asc())
    page_count = mode_templates.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ModeTemplatePublicSchema.model_validate(x) for x in mode_templates],
    }
    return response


@router.post('/mode_templates', response_model=ModeTemplatePublicSchema)
async def create_mode_template(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ModeTemplateCreateSchema,
):
    """
    Создать шаблон может администратор компании отчета либо системный администратор.
    """
    report = Report.get_or_none(Report.id == data.report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверка прав доступа.
    if (
            not current_user.is_admin
            and
            not (current_user.company_id == report.integration.company.id and current_user.company_role == Company.Roles.ADMIN)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Активные колонки отчета.
    mode_questions = ModeQuestion.select().where(ModeQuestion.report == report, ModeQuestion.is_active == True)

    with main_db.atomic():
        mode_template = ModeTemplate.create(
            name=data.name,
            final_model=report.final_model,
            context=report.context,
        )
        for mq in mode_questions:
            ModeTemplateQuestion.create(mode_template=mode_template, question=mq)

    return mode_template


@router.put('/mode_templates/{mode_template_id}', response_model=ModeTemplatePublicSchema)
async def update_mode_template(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        mode_template_id: int,
        data: ModeTemplateUpdateSchema,
):
    mode_template = ModeTemplate.get_or_none(ModeTemplate.id == mode_template_id)
    if mode_template is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Шаблон отчета не найден.')

    mode_template = update_endpoint_object(mode_template, data, True)
    return mode_template
