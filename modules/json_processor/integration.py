import json
from copy import deepcopy
from typing import Optional

from beeline_portal import BeelinePBX
from beeline_portal.errors import BeelinePBXException
from loguru import logger
from pyrogram.types import Message

from config.config import FERNET_KEY
from data.models import Integration, User, IntegrationServiceName
from integrations.amo_crm.amo_api_core import AmoApiAuth
from integrations.bitrix.bitrix_api import Bitrix24
from modules.crypter import encrypt
from modules.exceptions import IntegrationConnectError, ObjectNotFoundError, IntegrationExistsError
from modules.json_processor.struct_checkers import is_create_integration_json


def create_or_update_amocrm_integration(message: Message, full_json: dict):
    """
    Создание интеграции с АМОЦРМ
    """
    telegram_id = full_json['telegram_id']

    db_user: User = User.get_or_none(tg_id=telegram_id)
    if not db_user:
        return message.reply(f"Пользователь с tg_id {telegram_id} не найден в БД.")

    account_id = full_json['account_id']
    json_data = full_json['data']

    integration = Integration.get_or_none(
        (Integration.account_id == account_id)
        & (Integration.service_name == IntegrationServiceName.AMOCRM)
    )
    if integration:
        i_data = json.loads(integration.data)
        # Обновление фильтров
        if json_data.get("access") and json_data.get("access").get("code"):
            i_data["access"] = json_data["access"]
        if json_data.get("filters"):
            i_data["filters"] = json_data["filters"]
        if json_data.get('crm_data'):
            i_data['crm_data'] = json_data['crm_data']
        if json_data.get('settings'):
            i_data['settings'] = json_data['settings']
        if telegram_id:
            integration.user = db_user
            integration.save()

        integration.data = json.dumps(i_data)
        integration.save()
        log_txt = f"Обновил интеграцию с AmoCRM. tg_id: {telegram_id}, integration_id: {integration.id}"

    else:
        integration: Integration = Integration.create(
            user=db_user,
            service_name=IntegrationServiceName.AMOCRM,
            account_id=account_id,
            data=json.dumps(json_data)
        )
        log_txt = f"Создал интеграцию с AmoCRM. tg_id: {telegram_id}, integration_id: {integration.id}"

    # Инициализация интеграции
    response = AmoApiAuth(integration, with_handle_auth=False).handle_auth()

    if response != "ok":
        logger.info(f"Ошибка интеграции с AmoCRM. {response}")
        return message.reply("⚠️ <b>Ошибка интеграции</b>\n" + str(response), disable_web_page_preview=True)

    logger.info(log_txt)
    message.reply(log_txt)
    return integration


def create_or_update_bitrix24_integration(message: Message, full_json: dict):
    """
    Создание интеграции с Bitrix24
    """
    telegram_id = full_json['telegram_id']

    db_user: User = User.get_or_none(tg_id=telegram_id)
    if not db_user:
        return message.reply(f"Пользователь с tg_id {telegram_id} не найден в БД.")

    account_id = full_json['account_id']
    json_data = full_json['data']
    wh_url = json_data['access']['webhook_url']

    integration = Integration.get_or_none(
        (Integration.account_id == account_id)
        & (Integration.service_name == IntegrationServiceName.BITRIX24)
    )
    if integration:
        i_data = json.loads(integration.data)
        # Обновление фильтров
        if json_data.get("access"):
            i_data["access"] = json_data["access"]
            i_data['access']['webhook_url'] = encrypt(i_data['access']['webhook_url'], FERNET_KEY)
        if json_data.get("filters"):
            i_data["filters"] = json_data["filters"]
        if json_data.get('crm_data'):
            i_data['crm_data'] = json_data['crm_data']
        if json_data.get('settings'):
            i_data['settings'] = json_data['settings']
        if telegram_id:
            integration.user = db_user
            integration.save()

        integration.data = json.dumps(i_data)
        integration.save()
        log_txt = f"Обновил интеграцию с Bitrix24. tg_id: {telegram_id}, integration_id: {integration.id}"

    else:
        i_data = full_json['data']
        i_data['access']['webhook_url'] = encrypt(i_data['access']['webhook_url'], FERNET_KEY)
        integration: Integration = Integration.create(
            user=db_user,
            service_name=IntegrationServiceName.BITRIX24,
            account_id=account_id,
            data=json.dumps(i_data)
        )
        log_txt = f"Создал интеграцию с Bitrix24. tg_id: {telegram_id}, integration_id: {integration.id}"

    # Проверка интеграции
    response = Bitrix24(wh_url).check_integration()

    if response != "ok":
        logger.info(f"Ошибка интеграции с Bitrix24. {response}")
        return message.reply("⚠️ <b>Ошибка интеграции</b>\n" + str(response), disable_web_page_preview=True)

    logger.info(log_txt)
    message.reply(log_txt)
    return integration


def create_or_update_beeline_integration(
        full_json: dict,
        message: Optional[Message] = None,
) -> Optional[Integration]:
    """
    Создание интеграции с Beeline (или обновление существующей).
    """
    telegram_id = full_json['telegram_id']
    account_id = full_json['account_id']

    user = User.get_or_none(tg_id=telegram_id)
    if user is None:
        logger.error(f'Пользователь с tg_id {telegram_id} не найден в БД.')
        if message:
            message.reply(f'Пользователь с tg_id {telegram_id} не найден в БД.')
        return None

    # Проверка интеграции
    token = full_json['data']['access']['token']
    client = BeelinePBX(token)
    try:
        client.get_abonents()
    except Exception as ex:
        logger.error(f'Ошибка интеграции с Beeline. {ex}')
        if message:
            message.reply(f'⚠️ <b>Ошибка интеграции</b>\n{ex}', disable_web_page_preview=True)
        return None

    # Подготавливаем данные для поля `data`, шифруем необходимые поля.
    new_data = deepcopy(full_json['data'])
    new_data['access']['token'] = encrypt(new_data['access']['token'], FERNET_KEY)

    integration, created = Integration.get_or_create(
        account_id=account_id,
        service_name=IntegrationServiceName.BEELINE,
        defaults={
            'user': user,
            'data': json.dumps(new_data),
        }
    )
    if created:
        log_txt = f'Создал интеграцию с Beeline. tg_id: {telegram_id}, integration_id: {integration.id}'
    else:
        integration.user = user
        integration.data = json.dumps(new_data)
        integration.save()
        log_txt = f'Обновил интеграцию с Beeline. tg_id: {telegram_id}, integration_id: {integration.id}'

    logger.info(log_txt)
    if message:
        message.reply(log_txt)

    return integration


def create_or_update_integration(message: Message, full_json: dict) -> Integration:
    """
    Создание интеграции с АМОЦРМ
    """
    telegram_id = full_json['telegram_id']
    account_id = full_json['account_id']
    service_name = full_json['service_name']
    data = full_json['data']

    db_user: User = User.get_or_none(tg_id=telegram_id)
    if not db_user:
        return message.reply(f"Пользователь с tg_id {telegram_id} не найден в БД.")

    integration = Integration.get_or_none(account_id=account_id)
    if integration:
        integration.data = json.dumps(data)
        integration.save()
        log_txt = f"Обновил интеграцию типа {service_name}. tg_id: {telegram_id}, integration_id: {integration.id}"
    else:
        integration: Integration = Integration.create(
            user=db_user,
            service_name=service_name,
            account_id=account_id,
            data=json.dumps(data)
        )
        log_txt = f"Создал интеграцию типа {service_name}. tg_id: {telegram_id}, integration_id: {integration.id}"

    logger.info(log_txt)
    message.reply(log_txt)

    return integration


def create_integration_with_json(message: Message, full_json: dict):
    """
    Создание интеграции
    """
    if not is_create_integration_json(full_json):
        return message.reply("Некорректный json файл")

    service_name = full_json.get("service_name", "")

    if service_name == IntegrationServiceName.AMOCRM:
        create_or_update_amocrm_integration(message, full_json)
    elif service_name == IntegrationServiceName.BITRIX24:
        create_or_update_bitrix24_integration(message, full_json)
    elif service_name == IntegrationServiceName.BEELINE:
        create_or_update_beeline_integration(full_json, message)
    elif service_name == IntegrationServiceName.SIPUNI:
        create_or_update_integration(message, full_json)
    elif service_name == "custom":
        create_or_update_integration(message, full_json)


class IntegrationConstructor:

    """
    Универсальный класс для создания и обновления интеграций разных систем:
    – Bitrix24;
    – AmoCRM;
    – Beeline;
    – SipUni;
    – Custom.
    """

    def __init__(
            self,
            telegram_id: int,
            account_id: str,
            i_data: dict,
            service_name: IntegrationServiceName,
    ) -> None:
        self.telegram_id = telegram_id
        self.account_id = account_id
        self.data = i_data
        self.service_name = service_name

    def _check_connection(
            self,
            integration: Integration,
    ) -> bool:
        """
        Проверка подключения к CRM/телефонии.
        """
        if self.service_name == IntegrationServiceName.AMOCRM:
            response = AmoApiAuth(integration, with_handle_auth=False).handle_auth()
            if response != 'ok':
                raise IntegrationConnectError(f'Не удалось подключиться к AmoCRM. {response}')

        elif self.service_name == IntegrationServiceName.BITRIX24:
            webhook_url = integration.get_decrypted_access_field('webhook_url')
            response = Bitrix24(webhook_url).check_integration()
            if response != 'ok':
                raise IntegrationConnectError(f'Не удалось подключиться к Bitrix24. {response}')

        elif self.service_name == IntegrationServiceName.BEELINE:
            access_token = integration.get_decrypted_access_field('token')
            client = BeelinePBX(access_token)
            try:
                client.get_abonents()
            except BeelinePBXException as ex:
                raise IntegrationConnectError(f'Не удалось подключиться к Beeline. {type(ex)}')

        return True

    def create(
            self,
    ) -> Integration:
        """
        Создает интеграцию из JSON файла.
        Шифрует необходимые поля в зависимости от типа интеграции.
        Возвращает ID созданной интеграции.
        """
        integration = Integration.get_or_none(
            (Integration.account_id == self.account_id)
            & (Integration.service_name == self.service_name)
        )
        if integration is not None:
            raise IntegrationExistsError(f'Интеграция "{self.service_name.value}" с account_id={self.account_id} уже существует.')

        new_user = User.get_or_none(tg_id=self.telegram_id)
        if new_user is None:
            raise ObjectNotFoundError(f'Не удалось найти пользователя с tg_id={self.telegram_id}.')

        # Формируем новое значение поля data.
        new_data = deepcopy(self.data)
        if self.service_name == IntegrationServiceName.AMOCRM:
            new_data['access']['access_token'] = encrypt(new_data['access']['access_token'], FERNET_KEY)
            new_data['access']['refresh_token'] = encrypt(new_data['access']['refresh_token'], FERNET_KEY)
        elif self.service_name == IntegrationServiceName.BITRIX24:
            new_data['access']['webhook_url'] = encrypt(new_data['access']['webhook_url'], FERNET_KEY)
        elif self.service_name == IntegrationServiceName.BEELINE:
            new_data['access']['token'] = encrypt(new_data['access']['token'], FERNET_KEY)

        # Создаем интеграцию, но сохраняем в базу только после проверки связи с CRM/телефонией.
        integration = Integration(
            user=new_user,
            service_name=self.service_name,
            account_id=self.account_id,
            data=json.dumps(new_data),
        )
        self._check_connection(integration)
        integration.save()

        return integration

    def update(
            self,
            integration: Optional[Integration] = None,
    ) -> Integration:
        """
        Обновляет интеграцию.
        Возвращает ID обновлённой интеграции.
        """
        if integration is None:
            integration = Integration.get_or_none(
                (Integration.account_id == self.account_id)
                & (Integration.service_name == self.service_name)
            )
            if integration is None:
                raise ObjectNotFoundError(f'Интеграция "{self.service_name.value}" с account_id={self.account_id} не найдена.')

        if integration.account_id != self.account_id:
            integration.account_id = self.account_id

        if integration.user is None or integration.user.tg_id != self.telegram_id:
            new_user = User.get_or_none(tg_id=self.telegram_id)
            if new_user is None:
                raise ObjectNotFoundError(f'Не удалось найти пользователя с tg_id={self.telegram_id}.')
            integration.user = new_user

        integration.data = json.dumps(self.data)

        # Если удалось подключиться с новыми данными, сохраняем изменения в БД.
        self._check_connection(integration)
        integration.save()

        return integration
