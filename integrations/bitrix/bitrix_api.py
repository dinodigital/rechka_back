from typing import Optional, List
from urllib.parse import urlparse

import bitrix24

from integrations.bitrix.bx_models import BxWhData
from integrations.bitrix.exceptions import DataIsNotReadyError
from integrations.bitrix.models import CRMEntityType, CRMEntityTypeID


class Bitrix24:
    def __init__(self, webhook):
        self.bx24 = bitrix24.Bitrix24(webhook)
        self.domain = self.extract_domain(webhook)

    def check_integration(self):
        """
        Проверяет интеграцию с битрикс24

        :return: True, если интеграция существует
        """
        try:
            self.get_users()
            return "ok"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def extract_domain(webhook: str) -> str:
        """
        Возвращает домен из webhook
        """
        return urlparse(webhook).hostname

    def get_call_info(self, call_id) -> dict:
        """
        Возвращает информацию о звонке по его ID.
        """
        bx_method = "voximplant.statistic.get"
        bx_filter = {"CALL_ID": call_id}
        response = self.bx24.callMethod(bx_method, filter=bx_filter)

        if response[0].get("RECORD_FILE_ID") is None:
            raise DataIsNotReadyError('Звонок еще не загрузился в Битрикс')

        return response[0]

    def get_file_info(self, file_id):
        """
        Возвращает информацию о файле

        :param file_id: ID файла
        :return: информация о файле
        """
        bx_method = "disk.file.get"
        response = self.bx24.callMethod(bx_method, id=file_id)
        return response

    def get_lead(self, lead_id):
        """
        Возвращает информацию о лиде

        :param lead_id: ID лида
        :return: json с информацией о лиде

        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/leads/crm-lead-get.html
        """
        bx_method = "crm.lead.get"
        response = self.bx24.callMethod(bx_method, id=lead_id)
        return response

    def get_deal(self, deal_id):
        """
        Возвращает информацию о сделке

        :param deal_id: ID сделки
        :return: json с информацией о сделке

        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/deals/crm-deal-get.html
        """
        bx_method = "crm.deal.get"
        response = self.bx24.callMethod(bx_method, id=deal_id)
        return response

    def get_contact(self, contact_id):
        """
        Возвращает информацию о контакте

        :param contact_id: ID контакта
        :return: json с информацией о контакте

        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/contacts/crm-contact-get.html
        """
        bx_method = 'crm.contact.get'
        response = self.bx24.callMethod(bx_method, id=contact_id)
        return response

    def get_company(self, company_id):
        """
        Возвращает информацию о компании

        :param company_id: ID компании
        :return: json с информацией о компании

        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/companies/crm-company-get.html
        """
        bx_method = 'crm.company.get'
        response = self.bx24.callMethod(bx_method, id=company_id)
        return response

    def get_department(self, department_id) -> list:
        """
        Возвращает информацию о департаменте по ID департамента

        :param department_id: ID департамента
        :return: json с информацией о сделке
        """
        bx_method = "department.get"
        response: list = self.bx24.callMethod(bx_method, ID=department_id)
        return response

    def get_department_name_by_user_id(self, user_id) -> str:
        """
        Возвращает название департамента пользователя по его ID

        :param user_id: ID пользователя
        :return: Название департамента
        """
        user = self.get_users(user_id)
        department_id = user[0]['UF_DEPARTMENT'][0]
        department: list = self.get_department(department_id)
        department_name = department[0].get("NAME")
        return department_name if department_name else "Не указано"

    def get_calls_by_entity(self, entity_type: str, entity_id, min_duration: Optional[int] = None) -> list:
        """
        Возвращает список звонков для конкретной сущности.

        Документация:
            https://dev.1c-bitrix.ru/rest_help/scope_telephony/voximplant/statistic/voximplant_statistic_get.php
        """
        bx_method = "voximplant.statistic.get"
        bx_filter = {
            "CRM_ENTITY_TYPE": entity_type,
            "CRM_ENTITY_ID": entity_id
        }
        if min_duration is not None:
            bx_filter[">CALL_DURATION"] = min_duration
        bx_sort = "CALL_START_DATE"
        bx_order = "ASC"
        response = self.bx24.callMethod(bx_method, filter=bx_filter, sort=bx_sort, order=bx_order)
        return response

    def get_users(self, portal_user_id=None) -> List[dict]:
        """
        Возвращает список всех пользователей или конкретного пользователя по указанному PORTAL_USER_ID
        """
        bx_method = "user.get"
        if portal_user_id:
            response = self.bx24.callMethod(bx_method, id=portal_user_id)
        else:
            response = self.bx24.callMethod(bx_method)
        return response

    def get_users_as_text(self, sep: str = '\n') -> str:
        """
        Возвращает список пользователей в человекочитаемом виде.
        """
        users = self.get_users()

        lines = []
        for user in users:
            full_name = ' '.join(x for x in [user.get('NAME'), user.get('LAST_NAME')] if x)
            lines.append(f'{user["ID"]} - {full_name}')

        result = sep.join(lines)
        return result

    def get_user_name(self, portal_user_id) -> str:
        """
        Возвращает Имя ответственного по сделке по указанному PORTAL_USER_ID пользователя
        """
        user = self.get_users(portal_user_id)[0]
        first_name = user["NAME"]
        last_name = user["LAST_NAME"]
        return f"{first_name} {last_name}"

    def get_deal_list(self, entity_field_name, entity_id) -> list:
        """
        Возвращает список сделок для указанной сущности.
        Сделки сортируются по полю ID в порядке возрастания (от самой старой записи к самой новой).
        """
        method = 'crm.deal.list'
        params = {
            'filter': {
                entity_field_name: entity_id,
                'CLOSED': 'N',
            },
        }
        response = self.bx24.callMethod(method, params=params)
        return response

    def get_deal_list_by_contact_id(self, contact_id) -> list:
        """
        Возвращает список сделок для указанного контакта.
        """
        return self.get_deal_list('CONTACT_ID', contact_id)

    def get_deal_list_by_company_id(self, company_id) -> list:
        """
        Возвращает список сделок для указанной компании.
        """
        return self.get_deal_list('COMPANY_ID', company_id)

    def make_entity_url(self, entity_type: str, entity_id) -> str:
        return f'https://{self.domain}/crm/{entity_type.lower()}/details/{entity_id}/'

    def make_deal_url(self, deal_id) -> str:
        return self.make_entity_url(CRMEntityType.DEAL, deal_id)

    def make_lead_url(self, lead_id) -> str:
        return self.make_entity_url(CRMEntityType.LEAD, lead_id)

    def make_contact_url(self, contact_id) -> str:
        return self.make_entity_url(CRMEntityType.CONTACT, contact_id)

    def make_company_url(self, company_id) -> str:
        return self.make_entity_url(CRMEntityType.COMPANY, company_id)

    def get_activity_bindings_list(self, activity_id: int) -> List[dict]:
        """
        Получает список всех связей дела.
        """
        method = 'crm.activity.binding.list'
        params = {
            'activityId': activity_id,
        }
        response = self.bx24.callMethod(method, params=params)
        return response

    def get_activity_deal_id(self, activity_id: int) -> Optional[int]:
        """
        Возвращает ID сделки дела.
        """
        bindings = self.get_activity_bindings_list(activity_id)
        for item in bindings:
            if item['entityTypeId'] == CRMEntityTypeID.DEAL:
                return item['entityId']
        return None

    def add_comment(self, entity_type: str, entity_id: str, text: str):
        """
        Добавляет комментарий в карточку сущности.
        https://dev.1c-bitrix.ru/rest_help/crm/timeline/comment/crm_timeline_comment_add.php
        """
        method = 'crm.timeline.comment.add'
        params = {
            'fields': {
                'ENTITY_ID': entity_id,
                'ENTITY_TYPE': entity_type,
                'COMMENT': text,
            }
        }
        response = self.bx24.callMethod(method, params=params, http_method='POST')
        return response

    def add_deal(self, fields: dict) -> int:
        """
        Создает новую сделку.
        Возвращает ID созданного сделки.
        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/deals/crm-deal-add.html
        """
        method = 'crm.deal.add'
        params = {'fields': fields}
        response = self.bx24.callMethod(method, params=params, http_method='POST')
        return response

    def add_contact(self, fields: dict) -> int:
        """
        Создает новый контакт.
        Возвращает ID созданного контакта.
        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/contacts/crm-contact-add.html
        """
        method = 'crm.contact.add'
        params = {'fields': fields}
        response = self.bx24.callMethod(method, params=params, http_method='POST')
        return response

    def get_contact_list(self, field_name: str, field_value: str) -> list:
        """
        Возвращает список контактов по фильтру. Является реализацией списочного метода для контактов.
        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/contacts/crm-contact-list.html
        """
        method = 'crm.contact.list'
        params = {
            'filter': {field_name: field_value},
        }
        response = self.bx24.callMethod(method, params=params)
        return response

    def get_bitrix_base_data(self, bx_data: BxWhData, call_info) -> dict:
        """
        Возвращает базовую информацию о сделке
        """
        # ФИО ответственного
        responsible_user_name = self.get_user_name(bx_data.PORTAL_USER_ID)

        # URL сделки
        deal_url = None
        if call_info['CRM_ENTITY_TYPE'] in [CRMEntityType.CONTACT, CRMEntityType.COMPANY]:
            deal_id = self.get_activity_deal_id(bx_data.CRM_ACTIVITY_ID)
            if deal_id:
                deal_url = self.make_deal_url(deal_id)

        if deal_url is None:
            entity_id = call_info["CRM_ENTITY_ID"]

            if call_info['CRM_ENTITY_TYPE'] == CRMEntityType.CONTACT:
                deal_url = self.make_contact_url(entity_id)

            elif call_info['CRM_ENTITY_TYPE'] == CRMEntityType.LEAD:
                deal_url = self.make_lead_url(entity_id)

            elif call_info['CRM_ENTITY_TYPE'] == CRMEntityType.DEAL:
                deal_url = self.make_deal_url(entity_id)

            elif call_info['CRM_ENTITY_TYPE'] == CRMEntityType.COMPANY:
                deal_url = self.make_company_url(entity_id)
            else:
                deal_url = "Звонок не относится ни к контакту, ни к лиду, ни к сделке"

        # URL звонка
        file_info = self.get_file_info(call_info["RECORD_FILE_ID"])
        call_url = file_info["DOWNLOAD_URL"]

        return {
            "responsible_user_name": responsible_user_name,
            "call_url": call_url,
            "deal_url": deal_url
        }

    def get_crm_deal_userfield_list(self) -> list:
        # Возвращает список пользовательских полей сделок по фильтру.
        # https://dev.1c-bitrix.ru/rest_help/crm/cdeals/crm_deal_userfield_list.php
        bx_method = 'crm.deal.userfield.list'
        response = self.bx24.callMethod(bx_method)
        return response

    def get_crm_deal_userfield_get(self, id_: str) -> dict:
        # Возвращает пользовательское поле сделок по идентификатору.
        # https://dev.1c-bitrix.ru/rest_help/crm/cdeals/crm_deal_userfield_get.php
        bx_method = 'crm.deal.userfield.get'
        params = {'id': id_}
        response = self.bx24.callMethod(bx_method, params=params)
        return response

    def parse_bitrix_custom_fields(self, lang: str = 'ru') -> List[dict]:
        data = []

        # Получаем ID всех кастомных полей сделок.
        custom_fields = self.get_crm_deal_userfield_list()
        custom_field_ids = [x['ID'] for x in custom_fields]

        for field_id in custom_field_ids:
            custom_field = self.get_crm_deal_userfield_get(field_id)
            item = {
                'id': field_id,
                'name': custom_field['FIELD_NAME'],
                'value': custom_field['LIST_COLUMN_LABEL'][lang],
                'options': [
                    {'id': option['ID'], 'value': option['VALUE']}
                    for option in custom_field.get('LIST', [])
                ],
            }
            data.append(item)
        return data

    def generate_entity_link(self, crm_entity_type: str | None, crm_entity_id: str) -> str:
        """
        Генерирует ссылку на сущность в Bitrix24.

        :param crm_entity_type: Тип сущности (CONTACT, LEAD, DEAL, COMPANY)
        :param crm_entity_id: ID сущности
        :return: Ссылка на сущность
        """
        if crm_entity_type is None:
            return "Звонок не привязан ни к одной из сущностей"
        elif crm_entity_type in [CRMEntityType.CONTACT,
                                 CRMEntityType.LEAD,
                                 CRMEntityType.DEAL,
                                 CRMEntityType.COMPANY]:
            return self.make_entity_url(crm_entity_type, crm_entity_id)

        raise ValueError(f"Неизвестный тип сущности: {crm_entity_type}")

    def get_category_list(self, entity_type_id: CRMEntityTypeID) -> dict:
        """
        Получает список воронок (направлений), которые относятся к типу объекта CRM с идентификатором entity_type_id.
        """
        method = 'crm.category.list'
        params = {
            'entityTypeId': entity_type_id,
        }
        response = self.bx24.callMethod(method, params=params)
        return response

    def get_funnels(self) -> List[dict]:
        """
        Возвращает список воронок.
        """
        deal_categories = self.get_category_list(CRMEntityTypeID.DEAL)['categories']

        funnels = []
        for category in deal_categories:
            funnels.append({'ID': str(category['id']), 'NAME': category['name']})

        return funnels

    def get_stages(self, funnel_id: str) -> List[dict]:
        """
        Возвращает список этапов для определенной воронки сделки.
        """
        if funnel_id == '0':
            method = 'crm.status.list'
            params = {'filter': {'ENTITY_ID': 'DEAL_STAGE'}}
        else:
            method = 'crm.dealcategory.stage.list'
            params = {'id': funnel_id}

        stages = self.bx24.callMethod(method, params=params)
        return stages

    def get_funnels_with_stages(self) -> List[dict]:
        result = []
        funnels = self.get_funnels()

        for funnel in funnels:
            funnel_id = funnel['ID']
            funnel_name = funnel['NAME']

            stages = self.get_stages(funnel_id)

            result.append({
                'id': funnel_id,
                'name': funnel_name,
                'stages': stages,
            })
        return result

    def get_status_list(self, entity_id: str):
        """
        Возвращает список элементов справочника по фильтру.
        Является реализацией списочного метода для элементов справочников.
        Документация:
            https://apidocs.bitrix24.ru/api-reference/crm/status/crm-status-list.html
        """
        method = 'crm.status.list'
        params = {'filter': {'ENTITY_ID': entity_id}}
        return self.bx24.callMethod(method, params=params)

    def get_lead_stages(self) -> List[dict]:
        """
        Возвращает этапы лидов (они не привязаны к воронкам).
        """
        return self.get_status_list('STATUS')
