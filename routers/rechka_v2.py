from fastapi import APIRouter, Request, BackgroundTasks

from data.models import Task, User, RequestLog
from data.server_models import CustomCallRequest, CustomTaskRequest, AuthRequest
from helpers.logging_utils import log_with_context
from integrations.process_custom_webhook import has_access, process_custom_webhook, create_task
from routers.helpers import log_access_denied


router = APIRouter()


@router.post("/create_task")
async def create_task_webhook(call_request: CustomCallRequest,
                              request: Request,
                              background_tasks: BackgroundTasks):
    """
    Отправка звонка на анализ
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

    background_tasks.add_task(log_with_context(process_custom_webhook, context_id=context_id), call_request, db_task, is_v2=True, request_log_id=request_log_id)
    return {"status": 200, "call_id": call_request.call_id, "task_id": db_task.id}


@router.post("/check_task")
async def check_task_webhook(task_request: CustomTaskRequest,
                             request: Request):
    """
    Получение результатов анализа
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


@router.post('/user_balance')
async def user_balance(user_request: AuthRequest,
                       request: Request):

    if not has_access(user_request):
        log_access_denied(user_request, request)
        return {'status': 403, 'message': 'В доступе отказано'}

    user = User.get(tg_id=user_request.telegram_id)
    response = {
        'status': 200,
        'balance_in_seconds': user.get_seconds_balance(),
    }
    return response
