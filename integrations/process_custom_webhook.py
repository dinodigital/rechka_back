import requests
from loguru import logger
from peewee import InterfaceError
from requests import HTTPError
from requests.exceptions import RequestException

from config.const import CallbackAuthType
from data.models import Integration, User, Task, main_db
from data.server_models import CustomCallRequest
from modules.audio_processor import process_custom_webhook_audio
from modules.audiofile import Audiofile


def reconnect_to_db():
    # Закрываем текущее соединение, если оно есть
    if main_db.is_closed():
        main_db.connect()
        logger.info("Соединение с базой данных восстановлено.")


def send_to_callback(request: CustomCallRequest, db_task: Task):
    logger.info(f'Отправляем результат обработки звонка на коллбэк {request.callback_url}')

    status_data = db_task.get_status_data()
    payload = {
        'status': 200,
        'task_data': status_data,
    }
    integration = Integration.get_or_none(account_id=request.account_id)
    i_data = integration.get_data()

    callback_auth_type = i_data.get('callback_auth_type')
    callback_auth_secret = i_data.get('callback_auth_secret')
    logger.info(f'Тип авторизации запроса на коллбэк: "{callback_auth_type}"')

    if callback_auth_type == CallbackAuthType.HTTP_BASIC and callback_auth_secret:
        headers = {'Authorization': f'Basic {callback_auth_secret}'}
    else:
        headers = None

    try:
        requests.post(request.callback_url, json=payload, headers=headers)
    except RequestException as ex:
        logger.error(f'Не удалось отправить данные на коллбек {request.callback_url=} '
                     f'{db_task.id=} Ошибка: {type(ex)} {ex}.')
    else:
        logger.info(f'Данные успешно отправлены на коллбек {request.callback_url}')


def process_custom_webhook(request: CustomCallRequest, db_task: Task, is_v2: bool = False):
    """
    Обработчик кастомного вебхука
    """
    request_data_json = request.model_dump_json(exclude={'client_secret'})
    logger.info(f"Входящий кастомный вебхук {'v2' if is_v2 else 'v1'}. "
                f"Аккаунт: {request.account_id}. Задача: {db_task.id}. Вебхук: {request_data_json}.")
    try:
        audio = Audiofile().load_from_url(request.call_url, name=request.call_id)

        if is_v2:
            try:
                basic_data = [x['field_data'] for x in (request.fields_to_export or [])]
            except KeyError:
                raise Exception(f'Некорректный формат поля fields_to_export. '
                                f'Текущее значение: {request.fields_to_export}.')
        else:
            basic_data = None
        process_custom_webhook_audio(audio, db_task, basic_data=basic_data)

        if request.callback_url:
            send_to_callback(request, db_task)

    except Exception as ex:

        if isinstance(ex, HTTPError):
            status_message = 'Не удалось скачать аудиофайл.'
        else:
            status_message = 'Не удалось обработать запрос.'

        logger.error(f"[-] Кастомный вебхук {'v2' if is_v2 else 'v1'}. "
                     f"Аккаунт: {request.account_id}. {status_message}. Ошибка: {type(ex)} {ex}.")
        db_task.save_data({"report_status": "error", "status_message": status_message}, update=True)


def has_access(request) -> bool:
    """
    Проверка есть ли у пользователя доступ
    """
    try:
        integration = Integration.get_or_none(account_id=request.account_id)
    except InterfaceError as ex:
        logger.error(f"[-] Соединение к БД закрыто. Детали: {ex}")
        reconnect_to_db()  # Пытаемся переподключиться
        try:
            integration = Integration.get_or_none(account_id=request.account_id)  # Повторная попытка
        except Exception as e:
            logger.error(f"[-] Не удалось выполнить повторный запрос. Детали: {e}")
            integration = None
    if integration is None:
        return False

    i_data = integration.get_data()
    if i_data['client_secret'] != request.client_secret:
        return False

    user = User.get_or_none(tg_id=request.telegram_id)
    if user is None:
        return False

    return True


def create_task(request: CustomCallRequest):
    user = User.get(tg_id=request.telegram_id)
    task = Task.create(user=user)
    task.save_data({
        "telegram_id": request.telegram_id,
        "account_id": request.account_id,
        "task_id": task.id,
        "call_id": request.call_id,
        "call_url": request.call_url,
        "callback_url": request.callback_url,
        "fields_to_export": request.fields_to_export,
        "settings": {
            "advance_transcript": request.advance_transcript,
        },
        "result": {},
        "report_status": "in_progress"
    })
    return task
