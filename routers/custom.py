from fastapi import APIRouter, Request, BackgroundTasks

from data.models import Task, RequestLog
from data.server_models import CustomCallRequest, CustomTaskRequest
from helpers.logging_utils import log_with_context
from integrations.process_custom_webhook import has_access, create_task, process_custom_webhook
from routers.helpers import log_access_denied


router = APIRouter()


@router.post("/custom_webhook")
async def custom_webhook(call_request: CustomCallRequest,
                         request: Request,
                         background_tasks: BackgroundTasks):
    """
    Обработчик кастомного вебхука
    """
    if not has_access(call_request):
        log_access_denied(call_request, request)
        return {"status": 403, "message": "В доступе отказано"}

    db_task: Task = create_task(call_request)
    context_id = getattr(request.state, 'context_id', None)
    request_log_id = getattr(request.state, 'request_log_id', None)

    # Связываем запрос с задачей.
    if request_log_id is not None:
        db_task.request_log = RequestLog.get(id=request_log_id)
        db_task.save(only=['request_log'])

    background_tasks.add_task(log_with_context(process_custom_webhook, context_id=context_id), call_request, db_task, request_log_id=request_log_id)
    return {"status": 200, "call_id": call_request.call_id, "task_id": db_task.id}


@router.post("/custom_task")
async def custom_task(task_request: CustomTaskRequest,
                      request: Request):
    """
    Получение информации о задаче обработки вебхука
    """
    if not has_access(task_request):
        log_access_denied(task_request, request)
        return {"status": 403, "message": "В доступе отказано"}

    task = Task[task_request.task_id]
    task_data = task.get_data()
    if (
            task_data.get('account_id') != task_request.account_id
            or task_data.get('telegram_id') != task_request.telegram_id
    ):
        log_access_denied(task_request, request)
        return {"status": 403, "message": "В доступе отказано"}

    status_data = task.get_status_data()
    response = {
        'status': 200,
        'task_data': status_data
    }
    return response
