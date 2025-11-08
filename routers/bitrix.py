from pprint import pprint

from fastapi import APIRouter, Request, BackgroundTasks
from loguru import logger

from helpers.logging_utils import log_with_context
from integrations.bitrix.process_bitrix_webhook import process_bx_webhook_v2, parse_body_str


router = APIRouter()


@router.post("/bitrix_webhook")
async def bitrix_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик вебхука Bitrix24
    """
    response = await bitrix_webhook_v2(request, background_tasks)
    return response


@router.post("/bitrix_webhook/v2")
async def bitrix_webhook_v2(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик вебхука Bitrix24 V2
    """
    body = await request.body()
    context_id = getattr(request.state, 'context_id', None)
    request_log_id = getattr(request.state, 'request_log_id', None)
    background_tasks.add_task(log_with_context(process_bx_webhook_v2, context_id=context_id), body, request_log_id=request_log_id)

    return {"status": 200}


def test_bitrix_background_task(bx_webhook):
    logger.info('Запустили тестовую фоновую задачу Bitrix.')
    pprint(bx_webhook)


@router.post("/bitrix_test")
async def bitrix_webhook_test(request: Request, background_tasks: BackgroundTasks):
    """
    Тестовый обработчик вебхука Bitrix24
    """
    body = await request.body()
    body_str = body.decode("utf-8")
    bx_webhook = parse_body_str(body_str)
    pprint(bx_webhook)
    context_id = getattr(request.state, 'context_id', None)
    background_tasks.add_task(log_with_context(test_bitrix_background_task, context_id=context_id), bx_webhook)

    return {"status": 200}
