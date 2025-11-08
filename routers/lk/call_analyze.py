from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from starlette.responses import JSONResponse
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from data.models import Report, Task, User, RequestLog
from data.server_models import CustomCallRequest
from helpers.logging_utils import log_with_context
from integrations.process_custom_webhook import process_custom_webhook
from routers.auth import get_current_active_user
from schemas.call_analyze import CallAnalyzeCreateSchema
from schemas.user import UserModel


router = APIRouter()


@router.post('/call_analyzes')
async def create_call_analyze(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        request: Request,
        background_tasks: BackgroundTasks,
        data: CallAnalyzeCreateSchema,
):
    """
    Анализирует звонок через указанный отчет.
    Использует мод отчета.
    """
    report = Report.get_or_none(Report.id == data.report_id)
    if report is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Отчет не найден.')

    request_log_id = getattr(request.state, 'request_log_id', None)
    if request_log_id is not None:
        request_log = RequestLog.get(id=request_log_id)
    else:
        request_log = None

    task = Task.create(
        report=report,
        request_log=request_log,
        source='dashboard',
    )
    task_data = {
        "telegram_id": report.integration.user.tg_id,
        "account_id": report.integration.account_id,
        "result": {},
        "report_status": "in_progress",
    }

    if data.transcript_id is not None:
        # Анализ по transcript_id могут выполнять только администраторы системы.
        if not User.get(id=current_user.id).is_admin:
            raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail='В доступе отказано.')

        # Задача с нужным transcript_id. Часть метаданных будет перекопирована в новую задачу.
        transcript_task = Task.select().where(Task.transcript_id == data.transcript_id,
                                              Task.status == Task.StatusChoices.DONE).first()
        if transcript_task is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Задача с таким транскриптом не найдена.')
        if transcript_task.status != Task.StatusChoices.DONE:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail='Транскрипт с таким ID ранее не был корректно сохранен.')

        task.assembly_duration = transcript_task.assembly_duration
        task.transcript_id = transcript_task.transcript_id
        task.step = 'transcribed'

        call_url = transcript_task.file_url
    else:
        call_url = data.call_url

    task_data['call_url'] = call_url
    task.save_data(task_data)

    context_id = getattr(request.state, 'context_id', None)
    call_request = CustomCallRequest(
        account_id=report.integration.account_id,
        telegram_id=report.integration.user.tg_id,
        client_secret='', # нет необходимости, так как доступ проверяем через Depends.
        call_url=call_url,
    )
    background_tasks.add_task(log_with_context(process_custom_webhook, context_id=context_id), call_request, task)

    return JSONResponse(status_code=200, content={'task_id': task.id})
