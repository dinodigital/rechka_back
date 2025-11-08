import json
from typing import Optional, Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from peewee import fn
from starlette.status import HTTP_404_NOT_FOUND

from config import config as cfg
from data.models import Integration, Report, ModeTemplate, main_db, ModeQuestion, DefaultQuestions, \
    ModeQuestionCalcType, ModeQuestionType, Company, ModeTemplateQuestion
from routers.auth import get_current_active_user
from routers.helpers import update_endpoint_object
from routers.lk.integration import get_accessible_integration
from schemas.report import ReportPublicSchema, ReportCreateSchema, ReportUpdateSchema, ReportListItemPublicSchema, \
    ReportPartialUpdateSchema, ReportCRMQuestionsUpdateSchema
from schemas.user import UserModel


router = APIRouter()


@router.get('/reports/{report_id}', response_model=ReportPublicSchema)
async def get_report(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: int,
):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверка доступа через интеграцию.
    integration = get_accessible_integration(current_user.id, integration_id=report.integration.id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    return report


@router.get('/reports', response_model=Dict)
async def get_reports_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_id: Optional[int] = Query(None),
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    """
    Возвращает отчеты, доступные текущему пользователю.
    """
    db_query = Report.select().where(Report.is_archived == False)

    # Интеграции, доступные пользователю.
    integrations = get_accessible_integration(current_user.id)

    # Фильтр по компании.
    if company_id is not None:
        company = Company.get_or_none(Company.id == company_id)
        if company is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

        # Среди доступных интеграций оставляем с нужной компанией. Если она есть в списке.
        integrations = integrations.where(Integration.company == company)
        if not integrations.exists():
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    # Фильтр по интеграциям.
    db_query = db_query.where(Report.integration.in_(integrations))

    total_count = db_query.count()
    reports = db_query.limit(limit).offset(offset).order_by(Report.id.asc())
    page_count = reports.count()

    response = {
        'total_count': total_count,
        'count': page_count,
        'items': [ReportListItemPublicSchema.model_validate(x) for x in reports],
    }
    return response


@router.post('/reports', response_model=ReportPublicSchema)
async def create_report(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: ReportCreateSchema,
):
    # Проверка доступа через интеграцию.
    integrations = get_accessible_integration(current_user.id, integration_id=data.integration_id)
    integration = integrations.where(Integration.id == data.integration_id).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция не найдена.')

    if data.mode_template_id is not None:

        mode_template = ModeTemplate.get_or_none(ModeTemplate.id == data.mode_template_id)
        if mode_template is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Шаблон мода не найден.')

        final_model = mode_template.final_model
        context = mode_template.context

        # Колонки из шаблона, которые будут созданы в отчете.
        ai_mode_questions = [x.question for x in
            ModeTemplateQuestion
            .select(ModeTemplateQuestion.question)
            .join(ModeQuestion)
            .where(ModeTemplateQuestion.mode_template == mode_template,
                   ModeQuestion.calc_type == ModeQuestionCalcType.AI)
            .order_by(ModeQuestion.column_index)
        ]
    else:
        final_model = cfg.TASK_MODELS_LIST[-1]
        context = None
        ai_mode_questions = []

    with main_db.atomic():
        report = Report.create(
            name=data.name,
            integration=integration,
            description=data.description,
            final_model=final_model,
            context=context,
        )

        default_mq_kwargs = dict(report=report)

        # Создаем системные колонки.
        column_index = 1
        for q_params in DefaultQuestions.question_functions.values():
            ModeQuestion.create(
                is_active=True,
                short_name=q_params['title'],
                calc_type=ModeQuestionCalcType.CUSTOM,
                column_index=column_index,
                context='',
                question_text='',
                answer_type=q_params.get('answer_type', ModeQuestionType.STRING),
                **default_mq_kwargs,
            )
            column_index += 1

        # Создаем AI-колонки.
        for mq in ai_mode_questions:
            ModeQuestion.create(
                is_active=mq.is_active,
                short_name=mq.short_name,
                calc_type=ModeQuestionCalcType.AI,
                column_index=mq.column_index + column_index,
                data=mq.data,
                context=mq.context,
                question_text=mq.question_text,
                answer_type=mq.answer_type,
                answer_format=mq.answer_format,
                answer_options=mq.answer_options,
                variant_colors=mq.variant_colors,
                **default_mq_kwargs,
            )

    return report


@router.put('/reports/{report_id}', response_model=ReportPublicSchema)
async def update_report(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: int,
        data: ReportUpdateSchema,
):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверяем, разрешен ли пользователю доступ к редактированию текущей интеграции отчета.
    current_integration = get_accessible_integration(current_user.id, integration_id=report.integration.id, allow_company_user=False).first()
    if current_integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    if data.integration_id is not None and data.integration_id != report.integration.id:
        # Смена интеграции отчета разрешена только системному администратору.
        if not current_user.is_admin:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция не найдена.')

        # Проверяем, разрешен ли пользователю доступ к редактированию интеграции, с которой хотим связать отчет.
        new_integration = get_accessible_integration(current_user.id, integration_id=data.integration_id, allow_company_user=False).first()
        if new_integration is None:
            raise HTTPException(HTTP_404_NOT_FOUND, detail='Интеграция не найдена.')
    else:
        new_integration = current_integration

    report.name = data.name
    report.priority = data.priority
    report.description = data.description
    report.integration = new_integration
    report.sheet_id = data.sheet_id
    report.settings = data.settings
    report.filters = data.filters
    report.crm_data = data.crm_data
    report.final_model = data.final_model
    report.context = data.context
    report.active = data.active
    report.save()

    return report


@router.patch('/reports/{report_id}', response_model=ReportPublicSchema)
async def partial_update_report(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: int,
        data: ReportPartialUpdateSchema,
):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверяем, разрешен ли пользователю доступ к редактированию текущей интеграции отчета.
    current_integration = get_accessible_integration(current_user.id, integration_id=report.integration.id, allow_company_user=False).first()
    if current_integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    report = update_endpoint_object(report, data, False)
    return report



@router.put('/reports/{report_id}/crm_questions', response_model=Dict)
async def update_report_crm_questions(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: int,
        data: ReportCRMQuestionsUpdateSchema,
):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверяем, разрешен ли пользователю доступ к редактированию текущей интеграции отчета.
    integration = get_accessible_integration(current_user.id, integration_id=report.integration.id, allow_company_user=False).first()
    if integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Индексы всех активных колонок отчета.
    max_column_index = (
        ModeQuestion
        .select(fn.MAX(ModeQuestion.column_index).alias('max_column_index'))
        .where(
            (ModeQuestion.report == report) &
            (ModeQuestion.is_active == True)
        )
    ).scalar()

    # Незанятый индекс колонки, с которого будут нумероваться создаваемые колонки.
    if max_column_index is None:
        new_column_index = 1
    else:
        new_column_index = max_column_index + 1

    # ID активных CRM-колонок.
    active_question_ids = set()

    with main_db.atomic():

        for item in data.questions:
            answer_options = json.dumps([x.get('VALUE') for x in item.options])
            answer_type = ModeQuestionType.MULTIPLE_CHOICE if answer_options else ModeQuestionType.STRING

            # Создаем или активируем переданные пользователем колонки.
            mq, created = ModeQuestion.get_or_create(
                report=report,
                crm_entity_type=item.entity_type,
                crm_id=item.crm_id,
                defaults={
                    'is_active': True,
                    'short_name': item.name,
                    'calc_type': ModeQuestionCalcType.CRM,
                    'column_index': new_column_index,
                    'question_text': '',
                    'answer_type': answer_type,
                    'answer_options': answer_options,
                }
            )
            if created:
                # Если создали колонку (активную), то переходим к обработке следующей.
                new_column_index += 1
            else:
                # Если в базе уже была такая CRM-колонка, то активируем ее.
                if not mq.is_active:
                    mq.is_active = True
                if mq.short_name != item.name:
                    mq.short_name = item.name

                if answer_type != ModeQuestionType.MULTIPLE_CHOICE:
                    answer_options = None
                if mq.answer_options != answer_options:
                    mq.answer_options = answer_options

                mq.save(only=['is_active', 'short_name', 'answer_options'])

            active_question_ids.add(mq.id)

        # Отключаем все неактуальные колонки CRM.
        ModeQuestion.update(is_active=False).where(ModeQuestion.report == report,
                                                   ModeQuestion.is_active == True,
                                                   ModeQuestion.calc_type == ModeQuestionCalcType.CRM,
                                                   ModeQuestion.id.not_in(active_question_ids),
                                                   ).execute()

    response = {
        'active_crm_questions': list(active_question_ids),
    }
    return response


def clone_report(
        src_report: Report,
) -> Report:
    """
    Создает дубль отчета вместе со всеми активными колонками исходного отчета.
    """
    # Поля отчета, которые нужно скопировать без изменений.
    report_fields_to_copy = [
        'integration', 'description', 'settings', 'filters', 'crm_data', 'final_model', 'context',
    ]
    # Поля колонок, которые нужно скопировать без изменений.
    mode_question_fields_to_copy = [
        'is_active', 'short_name', 'calc_type', 'column_index', 'data', 'context', 'question_text', 'answer_type',
        'answer_format', 'answer_options', 'variant_colors', 'crm_entity_type', 'crm_id',
    ]
    # Активные колонки, которые нужно скопировать.
    mode_questions = ModeQuestion.select().where(ModeQuestion.report == src_report,
                                                 ModeQuestion.is_active == True)

    with main_db.atomic():

        # Создаем копию отчета.
        new_data = {f: getattr(src_report, f) for f in report_fields_to_copy}
        new_data.update({'active': False, 'name': f'[Копия] {src_report.name}'})
        new_report = Report.create(**new_data)

        # Создаем копии активных колонок.
        for mq in mode_questions:
            new_data = {f: getattr(mq, f) for f in mode_question_fields_to_copy}
            new_data.update({'report': new_report})
            ModeQuestion.create(**new_data)

    return new_report


@router.post('/reports/{report_id}/duplicate', response_model=ReportPublicSchema)
async def duplicate_report(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        report_id: int,
):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    # Проверяем, разрешен ли пользователю доступ к редактированию текущей интеграции отчета.
    report_integration = get_accessible_integration(current_user.id, integration_id=report.integration.id,
                                                    allow_company_user=False).first()
    if report_integration is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    new_report = clone_report(report)
    return new_report
