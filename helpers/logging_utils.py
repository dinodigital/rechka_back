import uuid
from functools import wraps

from loguru import logger


def log_with_context(func):
    """
    Обертка для функций, вызов которых нужно логировать с контекстом.
    Пример: задача, добавляемая в BackgroundTasks FastAPI.

    background_tasks.add_task(process_bx_webhook, body)
    ->
    background_tasks.add_task(log_with_context(process_bx_webhook), body)
    """

    @wraps(func)
    def wrapper(*args, **kwargs):

        # Уникальный идентификатор контекста для задачи.
        context_id = str(uuid.uuid4())

        with logger.contextualize(context_id=context_id):
            return func(*args, **kwargs)

    return wrapper
