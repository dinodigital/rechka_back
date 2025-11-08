from pprint import pprint

from fastapi import APIRouter, Request, BackgroundTasks

from helpers.logging_utils import log_with_context
from integrations.amo_crm.process_amo_webhook import process_amo_webhook_v1, process_amo_webhook_v2_report

router = APIRouter()


@router.post("/amo_test")
async def amo_webhook_test(request: Request, background_tasks: BackgroundTasks):
    """
    Тестовый обработчик вебхука AMOCRM
    """
    form_data = await request.form()
    pprint(form_data)
    # background_tasks.add_task(process_amo_webhook3, form_data)

    return {"status": 200}


@router.post("/amo_webhook")
async def amo_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик вебхука AMOCRM v1
    """
    form_data = await request.form()
    context_id = getattr(request.state, 'context_id', None)
    background_tasks.add_task(log_with_context(process_amo_webhook_v1, context_id=context_id), form_data, context_id=context_id)

    return {"status": 200}


@router.post("/amo_webhook/v2")
async def amo_webhook_v2(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик вебхука AMOCRM v2
    """
    response = await amo_webhook_v2_report(request, background_tasks)
    return response


@router.post("/amo_webhook/v2_report")
async def amo_webhook_v2_report(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик вебхука AMOCRM v2 с отчетами `Report`.
    """
    form_data = await request.form()
    context_id = getattr(request.state, 'context_id', None)
    background_tasks.add_task(log_with_context(process_amo_webhook_v2_report, context_id=context_id), form_data, context_id=context_id)

    return {"status": 200}
