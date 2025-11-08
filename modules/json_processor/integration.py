import json
from copy import deepcopy
from typing import Optional

from beeline_portal import BeelinePBX
from beeline_portal.errors import BeelinePBXException
from loguru import logger
from pyrogram.types import Message

from config.config import FERNET_KEY
from data.models import Integration, User, IntegrationServiceName, Company
from integrations.amo_crm.amo_api_core import AmoApiAuth
from integrations.bitrix.bitrix_api import Bitrix24
from integrations.mango.process import MangoClient
from integrations.sipuni.api import SipuniClient
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
            message.reply(f'⚠️ <b>Ошибка интеграции</b>\n{ex}')
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


def create_or_update_mango_integration(
        full_json: dict,
        message: Optional[Message] = None,
) -> Optional[Integration]:
    """
    Создание интеграции с Mango (или обновление существующей).
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
    api_key = full_json['data']['access']['api_key']
    api_salt = full_json['data']['access']['api_salt']
    client = MangoClient(api_key, api_salt)
    try:
        client.get_balance()
    except Exception as ex:
        logger.error(f'Ошибка интеграции с Mango. {ex}')
        if message:
            message.reply(f'⚠️ <b>Ошибка интеграции</b>\n{ex}')
        return None

    # Подготавливаем данные для поля `data`, шифруем необходимые поля.
    new_data = deepcopy(full_json['data'])
    new_data['access']['api_key'] = encrypt(new_data['access']['api_key'], FERNET_KEY)
    new_data['access']['api_salt'] = encrypt(new_data['access']['api_salt'], FERNET_KEY)

    integration, created = Integration.get_or_create(
        account_id=account_id,
        service_name=IntegrationServiceName.MANGO,
        defaults={
            'user': user,
            'data': json.dumps(new_data),
        }
    )
    if created:
        log_txt = f'Создал интеграцию с Mango. tg_id: {telegram_id}, integration_id: {integration.id}'
    else:
        integration.user = user
        integration.data = json.dumps(new_data)
        integration.save()
        log_txt = f'Обновил интеграцию с Mango. tg_id: {telegram_id}, integration_id: {integration.id}'

    logger.info(log_txt)
    if message:
        message.reply(log_txt)

    return integration


def create_integration_with_json(message: Message, full_json: dict):
    """
    Создание интеграции
    """
    if not is_create_integration_json(full_json):
        message.reply("Некорректный json файл")
        return None

    service_name = full_json.get("service_name", "")

    if service_name == IntegrationServiceName.AMOCRM:
        create_or_update_amocrm_integration(message, full_json)
    elif service_name == IntegrationServiceName.BITRIX24:
        create_or_update_bitrix24_integration(message, full_json)
    elif service_name == IntegrationServiceName.BEELINE:
        create_or_update_beeline_integration(full_json, message)
    elif service_name == IntegrationServiceName.SIPUNI:
        create_or_update_integration(message, full_json)
    elif service_name == IntegrationServiceName.MANGO:
        create_or_update_mango_integration(full_json, message)
    elif service_name == IntegrationServiceName.CUSTOM:
        create_or_update_integration(message, full_json)
    else:
        message.reply("Некорректный тип внешней системы")
    return None


class IntegrationConstructor:

    """
    Универсальный класс для создания и обновления интеграций разных систем:
    – Bitrix24;
    – AmoCRM;
    – Beeline;
    – SipUni;
    – Custom.
    """

    sensitive_fields = {
        IntegrationServiceName.BITRIX24: ['webhook_url'],
        IntegrationServiceName.BEELINE: ['token'],
        IntegrationServiceName.SIPUNI: ['application_token'],
    }

    def __init__(
            self,
            new_telegram_id: int,
            new_account_id: str,
            new_data: dict,
            new_service_name: IntegrationServiceName,
            new_company_id: Optional[int] = None,
    ) -> None:
        self.new_telegram_id = new_telegram_id
        self.new_account_id = new_account_id
        self.new_data = deepcopy(new_data)
        self.new_service_name = new_service_name
        self.new_company_id = new_company_id

    def _update_with_encrypted_fields(
            self,
            integration: Integration,
    ) -> None:
        """
        Шифрует чувствительные открытые данные.
        Обновляет self.new_data, используемый как источник новых данных .data интеграции.
        """
        if integration.data:
            if integration.service_name == IntegrationServiceName.AMOCRM:
                current_data = integration.get_data()

                if not self.new_data.get('access'):
                    if 'access' in current_data:
                        # Если access не передали, копируем полностью из текущей data.
                        self.new_data['access'] = deepcopy(current_data['access'])
                else:
                    # Если access передали, но не передали access_token и/или refresh_token,
                    # то берем их из существующей data.
                    if 'access_token' not in self.new_data['access']:
                        self.new_data['access']['access_token'] = current_data['access'].get('access_token')
                    if 'refresh_token' not in self.new_data['access']:
                        self.new_data['access']['refresh_token'] = current_data['access'].get('refresh_token')

        for field_name in self.sensitive_fields.get(integration.service_name, []):
            self.new_data['access'][field_name] = encrypt(self.new_data['access'][field_name], FERNET_KEY)

    def _check_connection(
            self,
            integration: Integration,
    ) -> None:
        """
        Проверка подключения к CRM/телефонии.
        Для AmoCRM обновляет токены через code (сохраняет их в self.new_data).
        """

        if integration.service_name == IntegrationServiceName.AMOCRM:
            # Если был передан code, то обновляем токены.
            if self.new_data.get('access', {}).get('code'):

                # Принудительно удаляем токены, даже если они не устарели.
                # Чтобы получить и сохранить новые.
                self.new_data['access'].pop('access_token', None)
                self.new_data['access'].pop('refresh_token', None)

                integration.data = json.dumps(self.new_data)
                amo_api = AmoApiAuth(integration, with_handle_auth=False, commit_on_update=False)
                response = amo_api.handle_auth()
                if response != 'ok':
                    raise IntegrationConnectError(f'Не удалось подключиться к AmoCRM. {response}')
                self.new_data = amo_api.data
                self.new_data['access']['code'] = None

        elif integration.service_name == IntegrationServiceName.BITRIX24:
            webhook_url = integration.get_decrypted_access_field('webhook_url')
            response = Bitrix24(webhook_url).check_integration()
            if response != 'ok':
                raise IntegrationConnectError(f'Не удалось подключиться к Bitrix24. {response}')

        elif integration.service_name == IntegrationServiceName.BEELINE:
            token = integration.get_decrypted_access_field('token')
            client = BeelinePBX(token)
            try:
                client.get_abonents()
            except BeelinePBXException as ex:
                raise IntegrationConnectError(f'Не удалось подключиться к Beeline. {type(ex)}')

        elif integration.service_name == IntegrationServiceName.SIPUNI:
            token = integration.get_decrypted_access_field('application_token')
            client = SipuniClient(integration.account_id, token)
            try:
                client.get_managers()
            except Exception as ex:
                raise IntegrationConnectError(f'Не удалось подключиться к SipUni. {type(ex)}')

    def create(
            self,
    ) -> Integration:
        """
        Создает интеграцию из JSON файла.
        Шифрует необходимые поля в зависимости от типа интеграции.
        Возвращает ID созданной интеграции.
        """
        integration = Integration.get_or_none(
            (Integration.account_id == self.new_account_id)
            & (Integration.service_name == self.new_service_name)
        )
        if integration is not None:
            raise IntegrationExistsError(f'Интеграция "{self.new_service_name.value}" '
                                         f'с account_id={self.new_account_id} уже существует.')

        # Создаем интеграцию без сохранения в БД.
        if self.new_company_id is not None:
            company = Company.get(id=self.new_company_id)
        else:
            company = None
        integration = Integration(
            company=company,
            service_name=self.new_service_name,
            account_id=self.new_account_id,
        )
        self.update(integration)

        return integration

    def update(
            self,
            integration: Integration,
    ) -> Integration:
        """
        Обновляет переданную интеграцию.
        Шифрует необходимые поля в зависимости от типа интеграции.
        Возвращает ID обновлённой интеграции.
        """
        if integration.account_id != self.new_account_id:
            integration.account_id = self.new_account_id

        if (self.new_telegram_id is not None
                and (integration.user is None or integration.user.tg_id != self.new_telegram_id)):
            new_user = User.get_or_none(tg_id=self.new_telegram_id)
            if new_user is None:
                raise ObjectNotFoundError(f'Не удалось найти пользователя с tg_id={self.new_telegram_id}.')
            integration.user = new_user

        if self.new_company_id is not None:
            if (not integration.company) or (integration.company.id != self.new_company_id):
                company = Company.get(id=self.new_company_id)
                integration.company = company

        self._update_with_encrypted_fields(integration)
        integration.data = json.dumps(self.new_data)

        self._check_connection(integration)
        integration.data = json.dumps(self.new_data)

        integration.save()

        return integration
