from typing import Union

from fastapi import Request
from loguru import logger

from data.server_models import CustomCallRequest, CustomTaskRequest, AuthRequest


def log_access_denied(
        data_request: Union[AuthRequest, CustomCallRequest, CustomTaskRequest],
        request: Request,
) -> None:
    request_data_json = data_request.model_dump_json(exclude={'client_secret'})
    logger.error(f'В доступе отказано. Код ответа: 403. '
                 f'[{request.method.upper()}] {request.url.path} {request_data_json=}')
    return None
