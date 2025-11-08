import json
from pprint import pprint
from typing import Optional, List, Tuple

import jwt
import requests
from datetime import datetime, timedelta

from loguru import logger
from pytz import timezone

from config import config
from config.const import AmoNoteType, AmoNoteTypeID
from data.models import Integration
from data.server_models import LeadNoteAmoWebhook, ContactNoteAmoWebhook, BaseNoteAmoWebhook, AmoLead
from helpers.integration_helpers import get_number_from_integration_settings
from integrations.const import CallTypeFilter
from modules.crypter import encrypt
from modules.numbers_matcher import phone_number_in_list


class AmoApiAuth:
    """
    Авторизация к API AmoCRM
    """

    def __init__(self, integration: Integration, with_handle_auth=True, commit_on_update: bool = True):
        """
        Инициализация класса Авторизация к API AmoCRM.

        :param integration: интеграция с amoCRM
        """
        self.integration = integration
        self.commit_on_update = commit_on_update
        self.data = json.loads(integration.data)
        self.access = self.data['access']
        self.subdomain = self.access["subdomain"]
        self.client_id = self.access["client_id"]
        self.client_secret = self.access["client_secret"]
        self.redirect_uri = self.access["redirect_uri"]
        self.code = self.access["code"]
        self.access_token = self.integration.get_decrypted_access_field('access_token', allow_empty=True)
        self.refresh_token = self.integration.get_decrypted_access_field('refresh_token', allow_empty=True)
        self.secret_code = self.access_token if self.access_token else self.code

        if with_handle_auth:
            self.handle_auth()

    def handle_auth(self):
        """
        Обработка авторизации.

        :return: True, если авторизация прошла успешно, и False в противном случае
        """
        if not self.access_token:
            return self.init_oauth2()
        elif self._is_expire(self.access_token):
            return self._get_new_tokens()
        else:
            return 'ok'

    @staticmethod
    def _is_expire(token: str):
        """
        Проверяет, истекло ли время жизни токена.

        :param token: токен для проверки
        :return: True, если истекло время жизни токена, и False в противном случае
        """
        token_data = jwt.decode(token, options={"verify_signature": False})
        exp = datetime.utcfromtimestamp(token_data["exp"])
        now = datetime.utcnow()

        return now >= exp

    def _save_tokens(self, access_token: str, refresh_token: str):
        """
        Сохраняет токены в интеграцию.

        :param access_token: новый токен доступа
        :param refresh_token: новый токен обновления
        """
        # Шифруем ключи и записываем в ключи data
        self.data['access']['access_token'] = encrypt(access_token, config.FERNET_KEY)
        self.data['access']['refresh_token'] = encrypt(refresh_token, config.FERNET_KEY)
        # Сохраняем в интеграцию
        self.integration.data = json.dumps(self.data)
        if self.commit_on_update:
            self.integration.save()

    def _get_new_tokens(self):
        """
        Получает новые токены.
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "redirect_uri": self.redirect_uri
        }
        url = f'https://{self.subdomain}.amocrm.ru/oauth2/access_token'
        response = requests.post(url, json=data)

        if response.status_code == 403:
            logger.error(f'Ошибка при авторизации: В доступе отказано. '
                         f'Интеграция: {self.integration.id}.')
            return response.text

        json_response = response.json()
        try:
            self.access_token = json_response["access_token"]
            self.refresh_token = json_response["refresh_token"]
            self._save_tokens(self.access_token, self.refresh_token)
            return "ok"
        except Exception as e:
            response_hint = f'{json_response.get("title")}: {json_response.get("detail")} ({json_response.get("hint")}).'
            logger.error(f"Ошибка при авторизации: {e}. "
                         f"Интеграция: {self.integration.id}. "
                         f"Ответ сервера: {response_hint}")
            return json_response

    def init_oauth2(self):
        """
        Инициализирует авторизацию.
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": self.secret_code,
            "redirect_uri": self.redirect_uri
        }
        url = f'https://{self.subdomain}.amocrm.ru/oauth2/access_token'
        response = requests.post(url, json=data)

        if response.status_code == 403:
            logger.error(f'Ошибка при авторизации: В доступе отказано. '
                         f'Интеграция: {self.integration.id}.')
            return response.text

        json_response = response.json()
        try:
            self.access_token = json_response["access_token"]
            self.refresh_token = json_response["refresh_token"]
            self._save_tokens(self.access_token, self.refresh_token)
            return "ok"
        except Exception as e:
            response_hint = f'{json_response.get("title")}: {json_response.get("detail")} ({json_response.get("hint")}).'
            logger.error(f"Ошибка при авторизации: {e}. "
                         f"Интеграция: {self.integration.id}. "
                         f"Ответ сервера: {response_hint}")
            return json_response


class AmoApiBase(AmoApiAuth):
    """
    Класс отправки запросов к API AmoCRM.

    Авторизация осуществляется через OAuth2.
    """

    def _make_headers(self):
        """
        Создает заголовки запроса. Если токен истек, то он обновляется.
        """
        if self._is_expire(self.access_token):
            self._get_new_tokens()

        access_token = f"Bearer {self.access_token}"

        return {"Authorization": access_token}

    def base_request(self, **kwargs) -> Optional[dict]:
        """
        Отправляет запрос к API AmoCRM.

        :param endpoint: URL-адрес ресурса
        :param type: тип запроса (get, post, patch)
        :param data: данные для запроса
        :param params: параметры для запроса
        """
        method, endpoint = kwargs['type'], kwargs['endpoint']

        url = f'https://{self.subdomain}.amocrm.ru{endpoint}'
        headers = self._make_headers()
        json_body = kwargs.get('data') if method.lower() != 'get' else None

        with requests.request(method, url,
                              headers=headers, json=json_body,
                              params=kwargs.get('params')) as response:
            if response.status_code == 200:
                return response.json()

            logger.error(f'Ошибка при запросе: {response.status_code} {endpoint}')
            return None


class AmoApi(AmoApiBase):

    @staticmethod
    def date_str_to_number(date_str):
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return int(date_obj.timestamp())

    def add_note(self, entity_id, text, entity_type="contacts"):
        """
        Добавить примечание в контакт
        """
        logger.info(f"Добавляю примечание в {entity_type} с id {entity_id}")

        endpoint = f"/api/v4/{entity_type}/{entity_id}/notes"

        data = [{
            'text': text,
            'note_type': AmoNoteType.COMMON,
        }]

        response = self.base_request(endpoint=endpoint, type="post", data=data)
        return response

    def update_lead_custom_fields(self, lead_id, fields_data):
        """
        Обновляет кастомные поля сделки в amoCRM.

        :param lead_id: ID сделки.
        :param fields_data: Список туплей в формате (field_id, data).
        """
        custom_fields_values = [{"field_id": field_id, "values": [{"value": data}]} for field_id, data in
                                fields_data]

        data = [{
            "id": int(lead_id),
            "custom_fields_values": custom_fields_values
        }]

        endpoint = "/api/v4/leads"
        response = self.base_request(type="patch", endpoint=endpoint, data=data)
        return response

    def get_lead_by_id(self, lead_id, with_contacts: bool = False):
        """
        Документация:
            https://www.amocrm.ru/developers/content/crm_platform/leads-api#lead-detail
        """
        endpoint = f"/api/v4/leads/{lead_id}"
        logger.info(f"Получаю лида по ID {lead_id} {with_contacts=}")
        if with_contacts:
            params = {'with': 'contacts'}
        else:
            params = None
        response: dict = self.base_request(endpoint=endpoint, type="get", params=params)
        return response

    def get_contact_by_id(self, contact_id, with_leads: bool = True):
        """
        Документация:
            https://www.amocrm.ru/developers/content/crm_platform/contacts-api#contact-detail
        """
        endpoint = f"/api/v4/contacts/{contact_id}"
        logger.info(f"Получаю контакт по ID {contact_id} {with_leads=}")
        if with_leads:
            params = {'with': "leads"}
        else:
            params = None
        response: dict = self.base_request(endpoint=endpoint, type="get", params=params)
        return response

    def get_company_by_id(self, company_id):
        """
        Документация:
            https://www.amocrm.ru/developers/content/crm_platform/companies-api#company-detail
        """
        endpoint = f"/api/v4/companies/{company_id}"
        logger.info(f"Получаю компанию по ID {company_id}")
        response: dict = self.base_request(endpoint=endpoint, type="get")
        return response

    def get_responsible_user_name(self, responsible_user_id):
        logger.info(f"Получаю Имя ответственного {responsible_user_id}")
        r = self.base_request(endpoint=f"/api/v4/users/{responsible_user_id}", type="get")
        return r['name'] if r is not None else "Пользователь удален из AmoCRM"

    def get_users(self) -> List[dict]:
        """
        Возвращает данные о пользователях (ID, ФИО).
        """
        endpoint = "/api/v4/users"
        logger.info("Получаю список пользователей")
        response: dict = self.base_request(endpoint=endpoint, type="get")

        if not response or "_embedded" not in response or "users" not in response["_embedded"]:
            logger.error("Не удалось получить список пользователей")
            return []

        users = response["_embedded"]["users"]
        result = [{'id': x['id'], 'name': x['name']}
                  for x in users]
        return result

    def get_users_as_text(self, sep: str = '\n') -> str:
        """
        Возвращает список пользователей в человекочитаемом виде.
        """
        users = self.get_users()
        result = sep.join(f"{x['id']} - {x['name']}"
                          for x in users)
        return result

    def get_entity_notes(self, entity_name: str, entity_id: int, limit: int = 100, extra_params: dict | None = None):
        """
        Документация amoCRM:
        https://www.amocrm.ru/developers/content/crm_platform/events-and-notes#notes-entity-list
        """
        endpoint = f"/api/v4/{entity_name}/{entity_id}/notes"
        params = {
            "limit": limit,
        }
        if extra_params:
            params.update(extra_params)
        response = self.base_request(endpoint=endpoint, type="get", params=params)
        return response

    def get_entity_call_notes(self, entity_name: str, entity_id: int, limit: int = 100):
        extra_params = {
            "filter[note_type]": f"{AmoNoteType.CALL_IN},{AmoNoteType.CALL_OUT}",
        }
        response = self.get_entity_notes(entity_name, entity_id, limit=limit, extra_params=extra_params)
        return response

    def get_lead_id_by_contact_id(self, contact_id, number=0):
        """
        Получает ID сделки, относящейся к контакту.

        :param contact_id: ID контакта.
        :param number: номер сделки.
        :return: ID сделки.
        """
        contact = self.get_contact_by_id(contact_id, with_leads=True)
        leads = contact['_embedded'].get("leads")
        try:
            lead_id = leads[number]['id'] if leads else 0
            logger.debug(f"[-] AmoCRM: get_lead number: {number}.")
        except IndexError as e:
            logger.error(f"[-] AmoCRM: get_lead {e}.")
            if len(leads) < number:
                number = -1
            else:
                number = 0
            logger.debug(f"[-] AmoCRM: get_lead number (except): {number}.")
            lead_id = leads[number]['id'] if leads else 0
        return lead_id

    def get_lead_id_from_webhook(self, webhook: BaseNoteAmoWebhook, number=0):

        if isinstance(webhook, LeadNoteAmoWebhook):
            lead_id = webhook.element_id
        elif isinstance(webhook, ContactNoteAmoWebhook):
            contact_id = webhook.element_id
            lead_id = self.get_lead_id_by_contact_id(contact_id, number=number)
        else:
            raise TypeError('Неизвестный тип вебхука')

        return lead_id

    def make_lead_link(self, lead_id):
        return f"https://{self.subdomain}.amocrm.ru/leads/detail/{lead_id}"

    def make_contact_link(self, contact_id):
        return f"https://{self.subdomain}.amocrm.ru/contacts/detail/{contact_id}"

    def get_lead_link_by_contact_id(self, contact_id, number=0):
        """
        Получает ссылку на страницу сделки, относящейся к контакту.

        :param contact_id: ID контакта.
        :param number: номер сделки.
        :return: Ссылка на страницу сделки.
        """
        lead_id = self.get_lead_id_by_contact_id(contact_id, number=number)
        if lead_id:
            link = self.make_lead_link(lead_id)
        else:
            link = "У контакта нет связанных сделок"
        return link

    def get_pipelines(self) -> List[dict]:
        """
        Возвращает воронки и этапы в виде словаря, где внутри каждой воронки перечислены все её этапы:
        {
            "id": "0",
            "name": "Воронка 0",
            "statuses": [
                {"id": 0, "name": "Этап 0"},
                {"id": 1, "name": "Этап 1"},
                {"id": 2, "name": "Этап 2"},
            ],
        }
        """
        result = []

        endpoint = '/api/v4/leads/pipelines'
        response: dict = self.base_request(endpoint=endpoint, type='get')

        pipelines = response['_embedded']['pipelines']
        for pipeline in pipelines:
            statuses = pipeline['_embedded']['statuses']
            result.append({
                'id': pipeline['id'],
                'name': pipeline['name'],
                'statuses': [{'id': x['id'], 'name': x['name']}
                             for x in statuses],
            })

        return result

    def get_pipelines_and_statuses(self):
        """
        Возвращает словарь id: name

        Пример:
        {
            "pipelines": {123: "Воронка 1", 123: "Воронка 2"},
            "statuses": {555: "Статус 1", 556: "Статус 2"}"}
        }
        """
        data = {
            'pipelines': {},
            'statuses': {}
        }

        pipelines_data = self.get_pipelines()
        for pipeline in pipelines_data:
            data['pipelines'][pipeline['id']] = pipeline['name']
            statuses = pipeline['statuses']
            for status in statuses:
                data['statuses'][status['id']] = status['name']

        return data

    def get_pipeline_and_status_names(self, lead_id) -> Tuple[str, str]:
        """
        Возвращает название воронки и название статуса.
        """
        pipelines_and_statuses = self.get_pipelines_and_statuses()
        pipelines = pipelines_and_statuses['pipelines']
        statuses = pipelines_and_statuses['statuses']

        lead = self.get_lead_by_id(lead_id)
        pipline_name = pipelines.get(lead['pipeline_id'])
        status_name = statuses.get(lead['status_id'])

        return pipline_name, status_name

    def get_pipelines_as_text(self, sep: str = '\n') -> str:
        lines = []

        pipelines = self.get_pipelines()
        for pipeline in pipelines:
            for status in pipeline['statuses']:
                lines.append(
                    f"Воронка {pipeline['name']} (id: {pipeline['id']}), Статус: {status['name']} (id: {status['id']})"
                )
        result = sep.join(lines)

        return result

    def print_pipelines_and_statuses(self) -> None:
        text = self.get_pipelines_as_text()
        print(text)

    def get_custom_fields(self, entity_type: str) -> List[dict]:
        """
        Документация:
            https://www.amocrm.ru/developers/content/crm_platform/custom-fields#Список-полей-сущности
        """
        endpoint = f'/api/v4/{entity_type}/custom_fields'
        response = self.base_request(endpoint=endpoint, type='get', data={'limit': 250})
        custom_fields = response['_embedded']['custom_fields']
        return custom_fields

    def get_leads_custom_fields(self) -> List[dict]:
        custom_fields = self.get_custom_fields('leads')
        result = []
        for f in custom_fields:
            result.append({
                'id': f['id'],
                'name': f['name'],
                'enums': f['enums'],
            })
        return result

    def get_all_calls_by_entity(self, entity_name: str, entity_id: int) -> List[dict]:
        """
        Возвращает список звонков для конкретной сущности.
        Отсортированный по возрастанию даты и времени создания.
        """
        notes = self.get_entity_call_notes(entity_name, entity_id)
        if notes:
            return sorted(notes['_embedded']['notes'], key=lambda x: x['created_at'])
        else:
            return []

    def get_first_call_by_entity_id(self, entity_name: str, entity_id: int, min_duration: int) -> dict:
        notes = self.get_all_calls_by_entity(entity_name, entity_id)
        # Из всех типов заметок оставляем только звонки.
        notes = [x for x in notes if x['note_type'] in [AmoNoteType.CALL_IN, AmoNoteType.CALL_OUT]]

        for note in notes:
            params = note['params']
            try:
                duration = int(params['duration'])
            # Несостоявшийся звонок.
            except TypeError:
                continue

            if duration > 0 and duration >= min_duration:
                return {
                    'call_url': params['link'],
                    'note_id': note['id']
                }
        return {}

    def check_call_filters(self, webhook: BaseNoteAmoWebhook, filters: dict, settings: dict, request_log_id: Optional[int] = None) -> bool:
        """
        Проверка фильтров:
        1. Типа примечания.
        2. Ненулевой длительности звонка.
        3. Ссылки на запись разговора.
        4. Направления звонка.
        5. Минимальной длительности звонка.
        6. Максимальной длительности звонка.
        7. На запрет на анализ телефонных номеров.
        8. Только первого звонка.
        9. По этапам сделки.
        10. По воронкам.
        11. Ответственных.
        12. Даты создания звонка. Максимум 24 часа назад.

        True – проверка всех фильтров пройдена успешно.
        False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
        """
        # Валидация типа примечания
        if webhook.note_type not in [AmoNoteTypeID.CALL_IN, AmoNoteTypeID.CALL_OUT]:
            try:
                note_type_name = AmoNoteTypeID(webhook.note_type).name
            except ValueError:
                note_type_name = 'Неизвестный тип'
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Не звонок. Note_type: {webhook.note_type} ({note_type_name})", request_log_id=request_log_id)
            return False

        # Валидация длительности звонка
        if webhook.DURATION == 0:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Звонок не состоялся. Duration: {webhook.DURATION}", request_log_id=request_log_id)
            return False

        # Валидация ссылки на запись разговора
        if not webhook.LINK:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Без ссылки на запись звонка. Вебхук: {webhook.__dict__}", request_log_id=request_log_id)
            return False

        # Валидация направления звонка.
        allowed_call_types = filters.get('allowed_call_types')
        if allowed_call_types:
            if (
                 (webhook.note_type == AmoNoteTypeID.CALL_IN and CallTypeFilter.INBOUND_VALUE not in allowed_call_types)
                 or
                 (webhook.note_type == AmoNoteTypeID.CALL_OUT and CallTypeFilter.OUTBOUND_VALUE not in allowed_call_types)
            ):
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Направление звонка: {webhook.note_type}. Фильтр: {allowed_call_types}", request_log_id=request_log_id)
                return False

        # Проверка минимальной длительности звонка
        min_call_duration = filters.get("min_duration")
        if min_call_duration and webhook.DURATION < min_call_duration:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Не проходим по мин. длительности. Факт. длит.: {webhook.DURATION}, мин: {min_call_duration}", request_log_id=request_log_id)
            return False

        # Проверка максимальной длительности звонка
        max_call_duration = filters.get("max_duration")
        if max_call_duration and webhook.DURATION > max_call_duration:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Не проходим по макс. длительности. Факт. длит.: {webhook.DURATION}, макс: {max_call_duration}", request_log_id=request_log_id)
            return False

        # Проверка на запрет на анализ телефонных номеров
        restricted_phones = filters.get("restricted_phones")
        if restricted_phones and phone_number_in_list(webhook.PHONE, restricted_phones):
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Установлен запрет на анализ телефона {webhook.PHONE}", request_log_id=request_log_id)
            return False

        # Проверка только первого звонка
        if filters.get("only_first_call"):
            first_call = self.get_first_call_by_entity_id(webhook.entity, webhook.element_id, filters['min_duration'])
            if not first_call or first_call['note_id'] != webhook.note_id:
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Не проходим по первому звонку. Element id: {webhook.element_id}", request_log_id=request_log_id)
                return False

        number = get_number_from_integration_settings(settings)

        # Фильтр по этапам сделки и воронкам
        statuses_in = filters.get("statuses_in")
        statuses_not_in = filters.get("statuses_not_in")
        pipelines_in = filters.get("pipelines_in")
        pipelines_not_in = filters.get("pipelines_not_in", [])

        if statuses_in or statuses_not_in or pipelines_in or pipelines_not_in:

            # Получаем ID сделки
            lead_id = self.get_lead_id_from_webhook(webhook, number=number)
            if not lead_id or lead_id == "У контакта нет связанных сделок":
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"У контакта нет связанных сделок.", request_log_id=request_log_id)
                return False

            lead_response = self.get_lead_by_id(lead_id)
            lead = AmoLead.model_validate(lead_response)

            # Фильтр по этапам сделки
            if statuses_in and lead.status_id not in statuses_in:
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Не проходим по статусу. Element id: {webhook.element_id}. Status_id: {lead.status_id}, Фильтр: {statuses_in=}", request_log_id=request_log_id)
                return False

            if statuses_not_in and lead.status_id in statuses_not_in:
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Не проходим по статусу. Element id: {webhook.element_id}. Status_id: {lead.status_id}, Фильтр: {statuses_not_in=}", request_log_id=request_log_id)
                return False

            # Фильтр по воронкам
            if pipelines_in and lead.pipeline_id not in pipelines_in:
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Не проходим по пайплайну. Pipeline_id: {lead.pipeline_id}, Фильтр: {pipelines_in}", request_log_id=request_log_id)
                return False

            # Исключение конкретных воронок
            if pipelines_not_in and lead.pipeline_id in pipelines_not_in:
                logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                            f"Воронка исключена. Pipeline_id: {lead.pipeline_id}, Исключенные воронки: {pipelines_not_in}", request_log_id=request_log_id)
                return False

        # Проверка ответственных
        responsible_users = [str(x).strip() for x in filters.get('responsible_users', [])]
        if responsible_users and str(webhook.main_user_id) not in responsible_users:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Ответственный: {webhook.main_user_id}, фильтр: {responsible_users=}", request_log_id=request_log_id)
            return False

        responsible_users_not_in = [str(x).strip() for x in filters.get('responsible_users_not_in', [])]
        if responsible_users_not_in and str(webhook.main_user_id) in responsible_users_not_in:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Ответственный: {webhook.main_user_id}, фильтр: {responsible_users_not_in=}", request_log_id=request_log_id)
            return False

        # Проверка даты создания звонка. Максимум 24 часа назад.
        tz_info = timezone(config.TIME_ZONE)
        yesterday_date = datetime.now(tz_info) - timedelta(days=1)
        wh_date = datetime.strptime(webhook.date_create, '%Y-%m-%d %H:%M:%S')
        wh_date = wh_date.replace(tzinfo=tz_info)

        if wh_date < yesterday_date:
            logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                        f"Не проходим по времени создания звонка. Время создания звонка: {wh_date}", request_log_id=request_log_id)
            return False

        logger.info(f"[+] ЗВОНОК AmoCRM - {webhook.account_subdomain} - id: {webhook.account_id}")
        return True


if __name__ == '__main__':
    amo = AmoApi(Integration[3])
    pprint(amo.get_lead_by_id(8189731))
