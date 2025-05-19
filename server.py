import json
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from config import config
from data.models import main_db
from helpers.db_helpers import select_db_1
from integrations.robokassa.proc_result_url import process_result_url
from routers.amocrm import router as amocrm_router
from routers.bitrix import router as bitrix_router
from routers.custom import router as custom_router
from routers.lk import router as lk_router, route_prefix as lk_route_prefix
from routers.rechka_v2 import router as rechka_v2_router

if config.API_SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=config.API_SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        environment=config.ENV,
    )


# https://github.com/Delgan/loguru?tab=readme-ov-file#easier-file-logging-with-rotation--retention--compression
logger.add(
    config.LOG_PATH,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> {extra}",
    rotation='50 MB',
    retention=10,
    compression='zip',
)


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
server.include_router(amocrm_router)
server.include_router(bitrix_router)
server.include_router(custom_router)
server.include_router(rechka_v2_router, prefix='/v2', tags=['v2'])
server.include_router(lk_router, prefix=lk_route_prefix, tags=['lk'])


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

        uvicorn.run(server, port=443, host='0.0.0.0',
                    ssl_keyfile=config.SSL_KEYFILE_PATH,
                    ssl_certfile=config.SSL_CERTFILE_PATH,
                    ssl_keyfile_password=config.SSL_KEYFILE_PASSWORD)

    else:
        uvicorn.run(server, port=80, host='0.0.0.0')
