import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.responses import JSONResponse

from config import config
from data.models import main_db, RequestLog
from helpers.db_helpers import select_db_1, DBLogHandler
from integrations.bitrix.exceptions import BadWebhookError as BitrixBadWebhookError
from integrations.robokassa.proc_result_url import process_result_url
from routers.amocrm import router as amocrm_router
from routers.auth import router as auth_router, route_prefix as auth_route_prefix
from routers.bitrix import router as bitrix_router
from routers.custom import router as custom_router
from routers.lk import main_router as lk_router
from routers.rechka_v2 import router as rechka_v2_router



FASTAPI_PORT = int(os.environ.get('FASTAPI_PORT', '443'))
# Каждый экземпляр сервера имеет свой лог-файл по номеру порта.
log_path = Path(config.LOG_PATH)
port_log_path = log_path.with_name(f'{log_path.stem}_{FASTAPI_PORT}{log_path.suffix}')

logger.remove()
logger.add(
    port_log_path,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> {extra}",
    rotation='50 MB',
    retention=10,
    compression='zip',
    enqueue=True,
)
db_handler = DBLogHandler()
logger.add(db_handler, enqueue=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Подключаемся к БД.')
    main_db.connect()

    logger.info('Запускаем FastApi.')
    yield

    logger.info('Закрываем соединение с БД.')
    main_db.close()


server = FastAPI(lifespan=lifespan)
server.add_middleware(
    CORSMiddleware,
    allow_origins=config.FASTAPI_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
server.include_router(amocrm_router, tags=['crm'])
server.include_router(bitrix_router, tags=['crm'])
server.include_router(custom_router, tags=['crm'])
server.include_router(rechka_v2_router, prefix='/v2', tags=['v2'])
server.include_router(auth_router, prefix=auth_route_prefix, tags=['auth'])
server.include_router(lk_router, prefix=auth_route_prefix)
server.mount('/static', StaticFiles(directory=config.FASTAPI_STATIC_DIR), name='static')


# Перехватывает все необработанные исключения FastAPI и записывает их в лог.
@server.exception_handler(Exception)
async def global_exception_handler(request: Request, ex: Exception):

    # Исключения, о которых не записывать сообщения в лог.
    exceptions_no_log = (BitrixBadWebhookError,)

    # Если ранее в request был добавлен context_id. Например, с помощью middleware('http').
    context_id = getattr(request.state, 'context_id', None)

    if not isinstance(ex, exceptions_no_log):
        request_log_id = getattr(request.state, 'request_log_id', None)
        message = (f'Во время обработки запроса (RequestLog.id={request_log_id}) произошла '
                   f'неизвестная ошибка: {type(ex)} "{ex}". {{context_id: {context_id}}}.')
        # Экранируем для loguru.
        message = message.replace('{', '{{').replace('}', '}}')
        logger.error(message, request_log_id=request_log_id)

    response = JSONResponse(status_code=500,
                            content={'message': 'Произошла неизвестная ошибка.',
                                     'code': context_id})
    return response


@server.middleware('http')
async def log_request(request: Request, call_next):

    """
    Сохраняет данные запроса в БД и генерирует context_id.
    """
    context_id = str(uuid.uuid4())

    path = str(request.url.path)
    paths_to_save = [
        '/bitrix_webhook',
        '/bitrix_webhook/v2',
        '/custom_webhook',
        '/v2/create_task',
    ]
    if path.rstrip('/') in paths_to_save:
        body = await request.body()
        # Бинарное содержимое запроса не сохраняем. На случай, если прислали файл.
        try:
            body_str = body.decode() if body else None
        except UnicodeDecodeError:
            logger.warning(f'Получен запрос с бинарным содержимым. context_id: "{context_id}".')
            body_str = None

        request_log = RequestLog.create(
            context_id=context_id,
            method=request.method,
            path=path,
            headers=json.dumps(dict(request.headers)),
            body=body_str,
        )
        request_log_id = request_log.id
    else:
        request_log_id = None

    # Сохраняем context_id в запросе, чтобы выводить в лог в дальнейшем.
    request.state.context_id = context_id
    request.state.request_log_id = request_log_id

    response = await call_next(request)

    return response


@server.post("/result_url")
async def root(request: Request, background_tasks: BackgroundTasks):
    """
    Обработчик resultURL
    """
    request_body = await request.body()
    background_tasks.add_task(process_result_url, request_body)


@server.get("/")
def simple_response():
    return {"message": "Hello, human"}


@server.get("/status")
def status_response():
    status = select_db_1()
    return {"status": 200 if status else 500}


@server.post("/json_test")
async def json_echo(request: Request):
    """
    Получает входящий запрос и выводит JSON
    """
    try:
        # Получаем тело запроса
        request_json = await request.json()
        # Возвращаем JSON
        return {"status": 200, "received_data": request_json}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}


if __name__ == '__main__':
    if config.PRODUCTION:
        if config.FASTAPI_HTTPS_ONLY:
            from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
            server.add_middleware(HTTPSRedirectMiddleware)

        uvicorn.run(server, port=FASTAPI_PORT, host='0.0.0.0',
                    ssl_keyfile=config.SSL_KEYFILE_PATH,
                    ssl_certfile=config.SSL_CERTFILE_PATH,
                    ssl_keyfile_password=config.SSL_KEYFILE_PASSWORD)

    else:
        uvicorn.run(server, port=config.FASTAPI_TEST_ENV_PORT, host='0.0.0.0')
