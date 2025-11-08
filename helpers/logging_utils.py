import uuid
from functools import wraps
from typing import Optional

from loguru import logger


def log_with_context(func, context_id: Optional[str] = None):
    """
    Обертка для функций, вызов которых нужно логировать с контекстом.
    Пример: задача, добавляемая в BackgroundTasks FastAPI.

    background_tasks.add_task(process_bx_webhook_v2, body)
    ->
    background_tasks.add_task(log_with_context(process_bx_webhook_v2), body)
    или
    background_tasks.add_task(log_with_context(process_bx_webhook_v2, context_id=context_id), body)
    """

    @wraps(func)
    def wrapper(*args, **kwargs):

        # Уникальный идентификатор контекста для задачи.
        cid = context_id or str(uuid.uuid4())

        with logger.contextualize(context_id=cid):
            return func(*args, **kwargs)

    return wrapper
