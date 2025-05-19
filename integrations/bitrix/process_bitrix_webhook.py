import time
from typing import List
from urllib.parse import parse_qs

from loguru import logger
from requests import HTTPError

from data.models import Integration, IntegrationServiceName, CallDownload, Task, Report
from helpers.db_helpers import not_enough_balance, create_task
from integrations.bitrix.bitrix_api import Bitrix24
from integrations.bitrix.bx_models import BxWhData
from integrations.bitrix.exceptions import BadWebhookError, DataIsNotReadyError
from integrations.bitrix.models import CRMEntityType, CallType
from misc.time import get_refresh_time
from modules.audio_processor import process_crm_call
from modules.audiofile import Audiofile
from modules.numbers_matcher import phone_number_in_list


def parse_body_str(body_str):
    """
    Парсинг вебхука Bitrix24
    """
    parsed_body = parse_qs(body_str)
    bx_webhook = {}

    for key, value in parsed_body.items():
        # Получение единственного значения из списка
        value = value[0]
        if '[' in key and ']' in key:
            # Обработка вложенных ключей, например, data[CALL_ID]
            main_key, sub_key = key.split('[')
            sub_key = sub_key.replace(']', '')
            if main_key not in bx_webhook:
                bx_webhook[main_key] = {}
            bx_webhook[main_key][sub_key] = value
        else:
            bx_webhook[key] = value

    return bx_webhook


def get_status_id(entity_type, entity, entity_deal):
    # Определяем ID статуса. У СДЕЛКИ и ЛИДА разные переменные статуса!
    # У компании и контакта берем ID статуса прикрепленной сделки.
    status_id = None
    if entity_type == CRMEntityType.LEAD:
        status_id = entity['STATUS_ID']
    elif entity_type == CRMEntityType.DEAL:
        status_id = entity['STAGE_ID']
    elif entity_deal:
        status_id = entity_deal['STAGE_ID']
    return status_id


def get_pipeline_id(entity_type, entity, entity_deal):
    pipeline_id = None
    if entity_type == CRMEntityType.DEAL:
        pipeline_id = entity['CATEGORY_ID']
    elif entity_deal:
        pipeline_id = entity_deal['CATEGORY_ID']
    return pipeline_id


def get_crm_fields_basic_data(domain, crm_fields, crm_entity_type, crm_entity_id, entity, entity_deal) -> List[str]:
    basic_data = []

    for field in crm_fields:
        lookup_entity = None

        # LEAD -> LEAD, DEAL -> DEAL, CONTACT -> CONTACT, COMPANY -> COMPANY.
        if (field['crm_entity_type'] == crm_entity_type
                and crm_entity_type in [CRMEntityType.LEAD, CRMEntityType.DEAL,
                                        CRMEntityType.CONTACT, CRMEntityType.COMPANY]):

            lookup_entity = entity

        # CONTACT -> DEAL, COMPANY -> DEAL.
        elif (field['crm_entity_type'] == CRMEntityType.DEAL
              and crm_entity_type in [CRMEntityType.CONTACT, CRMEntityType.COMPANY]):
            lookup_entity = entity_deal

        field_value = ''
        try:
            if lookup_entity is not None:
                field_value = lookup_entity[field['crm_field_id']]
        except KeyError:
            logger.warning(f'[-] Bitrix24: {domain}. '
                           f'CRM поле: {field["crm_field_id"]} не найдено в сущности {crm_entity_type} {crm_entity_id}')
        basic_data.append(field_value)

    return basic_data


def check_pipelines_and_statuses(domain, filters, crm_entity_type, entity, entity_deal) -> bool:
    """
    Проверка фильтров по воронкам и статусам.
    """

    error_text = None

    # Фильтр по воронкам
    pipelines_in = filters.get('pipelines_in') or []
    pipelines_not_in = filters.get('pipelines_not_in') or []

    if crm_entity_type == CRMEntityType.DEAL:
        deal_id = entity['ID']
    elif crm_entity_type in [CRMEntityType.CONTACT, CRMEntityType.COMPANY]:
        if entity_deal:
            deal_id = entity_deal['ID']
        else:
            deal_id = 'сделка не найдена'
    else:
        deal_id = None

    if pipelines_in or pipelines_not_in:
        pipeline_id = get_pipeline_id(crm_entity_type, entity, entity_deal)
        if pipeline_id is None:
            error_text = (f'У сущности нет воронки. Сущность: {crm_entity_type}. ID сделки: {deal_id}. '
                          f'Фильтр: {pipelines_in=} {pipelines_not_in=}')
        else:
            pipelines_in = [str(x) for x in pipelines_in]
            pipelines_not_in = [str(x) for x in pipelines_not_in]

            if pipelines_in and pipeline_id not in pipelines_in:
                error_text = (f"Воронка звонка не соответствует фильтру. "
                              f"Воронка: {pipeline_id}, фильтр: {pipelines_in=}")
            elif pipelines_not_in and pipeline_id in pipelines_not_in:
                error_text = (f"Воронка звонка не соответствует фильтру. "
                              f"Воронка: {pipeline_id}, фильтр: {pipelines_not_in=}")

    if error_text is None:

        # Фильтр по статусам
        statuses_in = filters.get('statuses_in') or []
        statuses_not_in = filters.get('statuses_not_in') or []

        if statuses_in or statuses_not_in:
            status_id = get_status_id(crm_entity_type, entity, entity_deal)
            statuses_in = [str(x) for x in statuses_in]
            statuses_not_in = [str(x) for x in statuses_not_in]

            if statuses_in and status_id not in statuses_in:
                error_text = (f"Статус звонка не соответствует фильтру. "
                              f"Статус: {status_id}, фильтр: {statuses_in=}. ID сделки: {deal_id}.")
            elif statuses_not_in and status_id in statuses_not_in:
                error_text = (f"Статус звонка не соответствует фильтру. "
                              f"Статус: {status_id}, фильтр: {statuses_not_in=}. ID сделки: {deal_id}.")

    if error_text:
        logger.info(f"[-] Bitrix24: {domain}. {error_text}")
        return False
    else:
        return True


def check_responsible_users(domain, bx_wh_data, filters) -> bool:
    error_text = None

    # Проверка ответственных
    responsible_users = filters.get("responsible_users") or []
    responsible_users_not_in = filters.get("responsible_users_not_in") or []

    if responsible_users or responsible_users_not_in:
        user_id = str(bx_wh_data.PORTAL_USER_ID)
        responsible_users = [str(x) for x in responsible_users]
        responsible_users_not_in = [str(x) for x in responsible_users_not_in]

        if responsible_users and user_id not in responsible_users:
            error_text = f"Ответственный: {user_id}, фильтр: {responsible_users=}"
        elif responsible_users_not_in and user_id in responsible_users_not_in:
            error_text = f"Ответственный: {user_id}, фильтр: {responsible_users_not_in=}"

    if error_text is not None:
        logger.info(f"[-] Bitrix24: {domain}. {error_text}")
        return False
    else:
        return True


def get_bitrix_call_info(bx24, call_id, webhook_url, body_str, api_router=None) -> dict:
    """
    Получает информацию о звонке по его ID.
    В случае ошибки создает повторную попытку загрузки звонка.
    """
    try:
        call_info = bx24.get_call_info(call_id)
    except (IndexError, DataIsNotReadyError) as ex:

        if isinstance(ex, IndexError):
            logger.error(f'Не удалось получить информацию о звонке. Проверьте вебхук. '
                         f'CALL ID: {call_id}. Domain: {bx24.domain}.')
        elif isinstance(ex, DataIsNotReadyError):
            logger.error('Звонок еще не загрузился в Битрикс.')
        CallDownload.create_or_update_from_webhook(call_id, body_str, webhook_url, api_router=api_router)

        raise BadWebhookError

    return call_info


def get_entity_and_entity_deal(bx24, entity_type, entity_id, activity_id) -> tuple:
    # Сущность события.
    if entity_type == CRMEntityType.CONTACT:
        entity = bx24.get_contact(entity_id)
    elif entity_type == CRMEntityType.COMPANY:
        entity = bx24.get_company(entity_id)
    elif entity_type == CRMEntityType.LEAD:
        entity = bx24.get_lead(entity_id)
    elif entity_type == CRMEntityType.DEAL:
        entity = bx24.get_deal(entity_id)
    else:
        entity = None

    # Сделка, прикрепленная к сущности.
    deal = None
    if entity_type in [CRMEntityType.CONTACT, CRMEntityType.COMPANY]:
        deal_id = bx24.get_activity_deal_id(activity_id)
        if deal_id:
            deal = bx24.get_deal(deal_id)
        else:
            logger.warning(f'Не удалось найти сделку сущности {activity_id=}.')

    return entity, deal

def process_bx_webhook(request_body: bytes):
    """
    Обработчик вебхука Bitrix24
    """
    body_str = request_body.decode("utf-8")
    bx_webhook = parse_body_str(body_str)
    domain = bx_webhook['auth']['domain']

    logger.debug(f"Bitrix24. body_str: {body_str}, bx_webhook: {bx_webhook}")
    logger.info(f"Входящий вебхук Bitrix24. Аккаунт: {domain}")

    bx_wh_data: BxWhData = BxWhData.model_validate(bx_webhook['data'])

    if not bx_wh_data.CALL_DURATION:
        error_msg = f"Call Duration = {bx_wh_data.CALL_DURATION}"
    elif not bx_wh_data.CALL_ID:
        error_msg = f"Вебхук не содержит Call ID"
    elif bx_wh_data.CALL_FAILED_CODE not in ['200', 'OTHER']:
        error_msg = f"Звонок не был успешен. Код: {bx_wh_data.CALL_FAILED_CODE}"
    else:
        error_msg = None

    if error_msg:
        logger.info(f"[-] Bitrix24. Аккаунт: {domain}. {error_msg}")
        return None

    # Валидация интеграции
    integration: Integration = Integration.get_or_none(
        (Integration.account_id == domain)
        & (Integration.service_name == IntegrationServiceName.BITRIX24)
    )
    if integration is None:
        return logger.info(f"[-] Bitrix24. Аккаунт: {domain}. Интеграция не найдена.")

    i_data = integration.get_data()
    filters = i_data.get("filters")

    # Первичная проверка длительности звонка
    min_call_duration = filters.get("min_duration")
    max_call_duration = filters.get("max_duration")
    if bx_wh_data.CALL_DURATION:
        if min_call_duration and bx_wh_data.CALL_DURATION < min_call_duration:
            return logger.info(f"[-] Bitrix24: {domain}. Длительность звонка: {bx_wh_data.CALL_DURATION}, фильтр: {min_call_duration}")
        if max_call_duration and bx_wh_data.CALL_DURATION > max_call_duration:
            return logger.info(f"[-] Bitrix24: {domain}. Длительность звонка: {bx_wh_data.CALL_DURATION}, фильтр: {max_call_duration}")

    passed_responsible_users_filters = check_responsible_users(domain, bx_wh_data, filters)
    if not passed_responsible_users_filters:
        return False

    # Проверка типа звонка
    allowed_call_types = filters.get('allowed_call_types')
    if allowed_call_types and not CallType.is_allowed_by_filters(bx_wh_data.CALL_TYPE, allowed_call_types):
        logger.info(f"[-] Bitrix24: {domain}. Тип звонка: {bx_wh_data.CALL_TYPE}, фильтр: {allowed_call_types}")
        return None

    webhook_url = integration.get_decrypted_access_field('webhook_url')
    bx24 = Bitrix24(webhook_url)

    call_info = get_bitrix_call_info(bx24, bx_wh_data.CALL_ID, webhook_url, body_str, api_router=None)

    crm_data = i_data.get("crm_data")
    if crm_data and crm_data.get("get_deal_timeout"):
        get_deal_timeout = crm_data.get("get_deal_timeout")
    else:
        get_deal_timeout = 0
    time.sleep(get_deal_timeout)

    crm_entity_type = call_info['CRM_ENTITY_TYPE']  # CONTACT, LEAD, DEAL, COMPANY
    crm_entity_id = call_info['CRM_ENTITY_ID']

    if (crm_entity_type is not None
            and crm_entity_type not in [CRMEntityType.CONTACT,
                                        CRMEntityType.LEAD,
                                        CRMEntityType.DEAL,
                                        CRMEntityType.COMPANY]):
        return logger.error(f"[!] Bitrix24: {domain}. Неизвестный тип сущности: {crm_entity_type}")

    # Фильтр по сущности CONTACT, LEAD, DEAL, COMPANY
    bitrix_entities_in: list = filters.get("bitrix_entities_in")
    if bitrix_entities_in and crm_entity_type not in bitrix_entities_in:
        return logger.info(f"[-] Bitrix24: {domain}. Не прошли фильтр сущности. Сущность: {crm_entity_type}, фильтр: {bitrix_entities_in}")

    # Фильтр по первому звонку
    if filters.get("only_first_call"):
        if crm_entity_type is None:
            logger.info(f"[-] Bitrix24: {domain}. Фильтр невозможен для сущности {crm_entity_type}.")
            return None
        else:
            # Получаем список звонков сущности
            entity_calls = bx24.get_calls_by_entity(crm_entity_type, crm_entity_id, min_call_duration)
            # Проверка наличия первого звонка
            if len(entity_calls) == 0:
                return logger.info(f"[-] Bitrix24: {domain}. У {crm_entity_type} {crm_entity_id} не найдено ни одного звонка")
            # Фильтрация по первому звонку
            first_call_with_min_duration_activity_id = int(entity_calls[0]["CRM_ACTIVITY_ID"])
            if first_call_with_min_duration_activity_id != bx_wh_data.CRM_ACTIVITY_ID:
                return logger.info(f"[-] Bitrix24: {domain}. Не первый звонок у сущности {crm_entity_type}.")

    restricted_phones = filters.get('restricted_phones')
    if restricted_phones and phone_number_in_list(bx_wh_data.PHONE_NUMBER, restricted_phones):
        logger.info(f"[-] Bitrix24: {domain}. Установлен запрет на анализ телефона {bx_wh_data.PHONE_NUMBER}")
        return None

    entity, entity_deal = get_entity_and_entity_deal(bx24, crm_entity_type, crm_entity_id, bx_wh_data.CRM_ACTIVITY_ID)

    passed_pipelines_and_statuses_filters = check_pipelines_and_statuses(domain,
                                                                         filters,
                                                                         crm_entity_type,
                                                                         entity,
                                                                         entity_deal)
    if not passed_pipelines_and_statuses_filters:
        return False

    bx_data = bx24.get_bitrix_base_data(bx_wh_data, call_info)

    if Task.select().where(Task.file_url == bx_data['call_url']).exists():
        logger.info(f"[-] Bitrix24 {bx_wh_data.PORTAL_USER_ID}: Уже обрабатывали данный файл: {bx_data['call_url']}")
        return None

    # Скачивание аудиофайла
    try:
        audio: Audiofile = Audiofile().load_from_url(bx_data['call_url'])
    except HTTPError:
        logger.error(f"[-] Bitrix24: {domain}. "
                     f"Не удалось скачать аудиофайл: {bx_data['call_url']}")
        return None

    # Проверка баланса по фактической длине аудиозаписи.
    if not_enough_balance(integration.user, audio.duration_in_sec):
        logger.info(f"[-] Bitrix24: {domain}. "
                    f"Недостаточно баланса {integration.user.seconds_balance}. Необходимо: {audio.duration_in_sec}")
        return None

    # Генерация ячеек для Google таблицы
    call_date = bx_wh_data.CALL_START_DATE.strftime("%Y-%m-%d %H:%M")
    basic_data = [get_refresh_time(),
                  call_date,
                  audio.duration_min_sec,
                  bx_data['responsible_user_name'],
                  bx_data['deal_url']]

    if crm_data:
        system_fields = crm_data.get("system_fields") or []

        # Выгрузка названия департамента
        if 'department' in system_fields:
            basic_data.append(bx24.get_department_name_by_user_id(bx_wh_data.PORTAL_USER_ID))

        # Выгрузка ссылки на сущность, к которой привязан звонок
        if 'entity_link' in system_fields:
            basic_data.append(bx24.generate_entity_link(crm_entity_type, crm_entity_id))

        # Выгрузка номера телефона в отчет.
        if 'phone_number' in system_fields:
            basic_data.append(bx_wh_data.PHONE_NUMBER.lstrip('+'))

        # Выгрузка типа звонка в отчет.
        if 'call_type' in system_fields:
            basic_data.append(CallType.get_readable_type(bx_wh_data.CALL_TYPE))

        # Выгрузка порядкового номера звонка в отчет.
        if 'index_number' in system_fields:
            entity_calls = bx24.get_calls_by_entity(crm_entity_type, crm_entity_id)
            basic_data.append(len(entity_calls))

        # Выгрузка названия воронки в отчет.
        if 'pipeline' in system_fields:
            pipeline_id = get_pipeline_id(crm_entity_type, entity, entity_deal)
            funnel_name = ''
            if pipeline_id is not None:
                funnels = bx24.get_funnels()
                for funnel in funnels:
                    if funnel['ID'] == pipeline_id:
                        funnel_name = funnel['NAME']
                        break
            basic_data.append(funnel_name)

        # Выгрузка названия этапа в отчет.
        if 'stage' in system_fields:
            stages = {}
            status_id = get_status_id(crm_entity_type, entity, entity_deal)

            if status_id is not None:
                # Получаем название этапа лида.
                if crm_entity_type == CRMEntityType.LEAD:
                    stages = bx24.get_lead_stages()
                    stages = {x['ID']: x['NAME'] for x in stages}

                # Получаем название этапа сделки.
                else: # CONTACT, DEAL, COMPANY

                    # Получаем воронку сделки.
                    pipeline_id = get_pipeline_id(crm_entity_type, entity, entity_deal)
                    if pipeline_id is not None:
                        stages = bx24.get_stages(pipeline_id)
                        stages = {x['ID' if pipeline_id == '0' else 'STATUS_ID']: x['NAME'] for x in stages}

            stage_name = stages.get(status_id, '')
            basic_data.append(stage_name)

        crm_fields = crm_data.get('crm_fields') or []
        crm_fields_basic_data = get_crm_fields_basic_data(domain,
                                                          crm_fields,
                                                          crm_entity_type,
                                                          crm_entity_id,
                                                          entity,
                                                          entity_deal)
        basic_data.extend(crm_fields_basic_data)

    # Фильтр по кастомным полям. Работает только со сделкой.
    custom_fields = filters.get('custom_fields', [])
    if crm_entity_type and custom_fields:

        # if crm_entity_type == CRMEntityType.LEAD:
        #     logger.info(f'[-] Bitrix24: {domain}. '
        #                 f'Кастомное поле. Неподходящий тип сущности: {crm_entity_type}')
        #     return False

        # Сущность, в карточке которой ищем соответствующие поля.
        if entity_deal:
            entity_with_custom_fields = bx24.get_deal(entity_deal['ID'])
        elif crm_entity_type == CRMEntityType.DEAL or crm_entity_type == CRMEntityType.LEAD:
            entity_with_custom_fields = entity
        else:
            entity_with_custom_fields = None

        if entity_with_custom_fields:

            for field in custom_fields:

                # Если кастомного поля нет в карточке сущности, то фильтр не проходит.
                field_name = field['name']
                if field_name not in entity_with_custom_fields:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name} не найдено в сущности {crm_entity_type} {crm_entity_id}')
                    return None
                value = entity_with_custom_fields[field_name]

                value_in = field.get('value_in')
                if value_in and value not in value_in:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name}, со значением: "{value}", фильтр value_in: {value_in}')
                    return None

                value_not_in = field.get('value_not_in')
                if value_not_in and value in value_not_in:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name}, со значением: "{value}", фильтр value_not_in: {value_not_in}')
                    return None

                logger.info(f'[+] Bitrix24: {domain}. Кастомное поле: {field_name}, со значением: "{value}"')

    # Вторичная проверка длительности звонка
    if (
            min_call_duration and audio.duration_in_sec < min_call_duration
            or
            max_call_duration and audio.duration_in_sec > max_call_duration
    ):
        logger.info(f"[-] Bitrix24: {domain}. Фактическая длительность звонка: {audio.duration_in_sec}, фильтр: {min_call_duration}-{max_call_duration}")
        to_save = bx_wh_data.CALL_DURATION > (audio.duration_in_sec * 5)
        if to_save:
            CallDownload.create_or_update_from_webhook(bx_wh_data.CALL_ID, body_str, webhook_url)
            logger.error(f'Звонок c Манго загрузился не полностью {audio.duration_in_sec}.')
        return logger.info(f"[-] Bitrix24: {domain}. Фактическая длительность звонка: {audio.duration_in_sec}, фильтр: {min_call_duration}-{max_call_duration}")

    task = create_task(user=integration.user,
                       initial_duration=bx_wh_data.CALL_DURATION,
                       duration_sec=audio.duration_in_sec,
                       file_url=audio.url)
    logger.info(f"Создал новый B24 Task {task.id}")

    # Анализ аудиозаписи и выгрузка отчета.
    string_report = process_crm_call(audio, integration.user, basic_data, task)

    # Оставляем комментарий о совершенном звонке в карточке сделки.
    # Если сделки нет, то в карточке контакта, компании или лида.
    if crm_entity_type is not None and filters.get('write_note'):
        if entity_deal:
            comment_entity_type = CRMEntityType.DEAL
            comment_entity_id = entity_deal['ID']
        else:
            comment_entity_type = crm_entity_type
            comment_entity_id = crm_entity_id
        bx24.add_comment(comment_entity_type, comment_entity_id, string_report)


def process_bx_webhook_v2(request_body: bytes):
    """
    Обработчик вебхука Bitrix24
    """
    body_str = request_body.decode("utf-8")
    bx_webhook = parse_body_str(body_str)
    domain = bx_webhook['auth']['domain']

    logger.debug(f"Bitrix24 V2. body_str: {body_str}, bx_webhook: {bx_webhook}")
    logger.info(f"Входящий вебхук Bitrix24 V2. Аккаунт: {domain}")

    bx_wh_data: BxWhData = BxWhData.model_validate(bx_webhook['data'])

    if not bx_wh_data.CALL_DURATION:
        return logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Call Duration = {bx_wh_data.CALL_DURATION}")

    if not bx_wh_data.CALL_ID:
        return logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Вебхук не содержит Call ID")

    # https://dev.1c-bitrix.ru/rest_help/scope_telephony/codes_and_types.php
    if bx_wh_data.CALL_FAILED_CODE not in ['200', 'OTHER']:
        logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Звонок не был успешен. Код: {bx_wh_data.CALL_FAILED_CODE}")
        return None

    # Валидация интеграции
    integration: Integration = Integration.get_or_none(
        (Integration.account_id == domain)
        & (Integration.service_name == IntegrationServiceName.BITRIX24)
    )
    if integration is None:
        return logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Интеграция не найдена.")

    reports = Report.select().where(
        (Report.integration == integration) & (Report.active == True)
    )

    reports_bypass_filters = []

    webhook_url = integration.get_decrypted_access_field('webhook_url')
    if reports:
        for report in reports:
            is_valid_report = report_bypass_filters(report=report, bx_wh_data=bx_wh_data, domain=domain,
                                                    body_str=body_str, webhook_url=webhook_url,
                                                    bx_webhook=bx_webhook)
            if is_valid_report:
                reports_bypass_filters.append(report)
    else:
        return logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Нет связанных отчётов.")

    if reports_bypass_filters:
        # Выбор report с минимальным значением priority
        highest_priority_report = min(reports_bypass_filters, key=lambda report_object: report_object.priority)
        logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Report с наивысшим приоритетом: ID={highest_priority_report.id}, "
                    f"Priority={highest_priority_report.priority}, Call ID={bx_wh_data.CALL_ID}.")
    else:
        return logger.info(f"[-] Bitrix24 V2. Аккаунт: {domain}. Нет отчётов, прошедших фильтры {bx_wh_data.CALL_ID}.")

    bx24 = Bitrix24(webhook_url)

    call_info = get_bitrix_call_info(bx24, bx_wh_data.CALL_ID, webhook_url, body_str, api_router='/bitrix_webhook/v2')

    filters = highest_priority_report.get_report_filters()
    settings = highest_priority_report.get_report_settings()
    crm_data = highest_priority_report.get_report_crm_data()

    bx_data = bx24.get_bitrix_base_data(bx_wh_data, call_info)

    # Скачивание аудиофайла
    try:
        audio: Audiofile = Audiofile().load_from_url(bx_data['call_url'])
    except HTTPError:
        logger.error(f"[-] Bitrix24 V2: {domain}. "
                     f"Не удалось скачать аудиофайл: {bx_data['call_url']}")
        return None

    # Проверка баланса по фактической длине аудиозаписи.
    if not_enough_balance(integration.user, audio.duration_in_sec):
        logger.info(f"[-] Bitrix24 V2: {domain}. "
                    f"Недостаточно баланса {integration.user.seconds_balance}. Необходимо: {audio.duration_in_sec}")
        return None

    min_call_duration = filters.get("min_duration")
    max_call_duration = filters.get("max_duration")

    # Вторичная проверка длительности звонка
    if (
            min_call_duration and audio.duration_in_sec < min_call_duration
            or
            max_call_duration and audio.duration_in_sec > max_call_duration
    ):
        to_save = bx_wh_data.CALL_DURATION > (audio.duration_in_sec * 5)
        if to_save:
            CallDownload.create_or_update_from_webhook(bx_wh_data.CALL_ID, body_str, webhook_url, api_router='/bitrix_webhook/v2')

            logger.error(f'Звонок c Манго загрузился не полностью {audio.duration_in_sec}.')
        return logger.info(f"[-] Bitrix24: {domain}. Фактическая длительность звонка: {audio.duration_in_sec}, фильтр: {min_call_duration}-{max_call_duration}")

    crm_entity_type = call_info['CRM_ENTITY_TYPE']  # CONTACT, LEAD, DEAL, COMPANY
    crm_entity_id = call_info['CRM_ENTITY_ID']

    task = create_task(user=integration.user,
                       initial_duration=bx_wh_data.CALL_DURATION,
                       duration_sec=audio.duration_in_sec,
                       file_url=audio.url)
    logger.info(f"Создал новый B24 V2 Task {task.id}")

    # Генерация ячеек для Google таблицы
    call_date = bx_wh_data.CALL_START_DATE.strftime("%Y-%m-%d %H:%M")
    basic_data = [get_refresh_time(),
                  call_date,
                  audio.duration_min_sec,
                  bx_data['responsible_user_name'],
                  bx_data['deal_url']]

    entity, entity_deal = get_entity_and_entity_deal(bx24, crm_entity_type, crm_entity_id, bx_wh_data.CRM_ACTIVITY_ID)

    if crm_data:
        system_fields = crm_data.get("system_fields") or []

        # Выгрузка названия департамента
        if 'department' in system_fields:
            basic_data.append(bx24.get_department_name_by_user_id(bx_wh_data.PORTAL_USER_ID))

        # Выгрузка ссылки на сущность, к которой привязан звонок
        if 'entity_link' in system_fields:
            basic_data.append(bx24.generate_entity_link(crm_entity_type, crm_entity_id))

        # Выгрузка номера телефона в отчет.
        if 'phone_number' in system_fields:
            basic_data.append(bx_wh_data.PHONE_NUMBER.lstrip('+'))

        # Выгрузка типа звонка в отчет.
        if 'call_type' in system_fields:
            basic_data.append(CallType.get_readable_type(bx_wh_data.CALL_TYPE))

        # Выгрузка порядкового номера звонка в отчет.
        if 'index_number' in system_fields:
            entity_calls = bx24.get_calls_by_entity(crm_entity_type, crm_entity_id)
            basic_data.append(len(entity_calls))

        # Выгрузка названия воронки в отчет.
        if 'pipeline' in system_fields:
            pipeline_id = get_pipeline_id(crm_entity_type, entity, entity_deal)
            funnel_name = ''
            if pipeline_id is not None:
                funnels = bx24.get_funnels()
                for funnel in funnels:
                    if funnel['ID'] == pipeline_id:
                        funnel_name = funnel['NAME']
                        break
            basic_data.append(funnel_name)

        # Выгрузка названия этапа в отчет.
        if 'stage' in system_fields:
            stages = {}
            status_id = get_status_id(crm_entity_type, entity, entity_deal)
            if status_id is not None:

                # Получаем название этапа лида.
                if crm_entity_type == CRMEntityType.LEAD:
                    stages = bx24.get_lead_stages()
                    stages = {x['ID']: x['NAME'] for x in stages}

                # Получаем название этапа сделки.
                else:  # CONTACT, DEAL, COMPANY

                    # Получаем воронку сделки.
                    pipeline_id = get_pipeline_id(crm_entity_type, entity, entity_deal)
                    if pipeline_id is not None:
                        stages = bx24.get_stages(pipeline_id)
                        stages = {x['ID' if pipeline_id == '0' else 'STATUS_ID']: x['NAME'] for x in stages}

            stage_name = stages.get(status_id, '')
            basic_data.append(stage_name)

        crm_fields = crm_data.get('crm_fields') or []
        crm_fields_basic_data = get_crm_fields_basic_data(domain,
                                                          crm_fields,
                                                          crm_entity_type,
                                                          crm_entity_id,
                                                          entity,
                                                          entity_deal)
        basic_data.extend(crm_fields_basic_data)


    # Анализ аудиозаписи и выгрузка отчета.
    string_report = process_crm_call(audio, integration.user, basic_data, mode=highest_priority_report.mode, task=task)

    # Оставляем комментарий о совершенном звонке в карточке сделки.
    # Если сделки нет, то в карточке контакта, компании или лида.
    if crm_entity_type is not None and settings.get('write_note'):
        if entity_deal:
            comment_entity_type = CRMEntityType.DEAL
            comment_entity_id = entity_deal['ID']
        else:
            comment_entity_type = crm_entity_type
            comment_entity_id = crm_entity_id
        bx24.add_comment(comment_entity_type, comment_entity_id, string_report)


def report_bypass_filters(report: Report, bx_wh_data: BxWhData, domain, body_str, webhook_url, bx_webhook) -> bool:
    filters = report.get_report_filters()
    settings = report.get_report_settings()
    crm_data = report.get_report_crm_data()

    # Первичная проверка длительности звонка
    min_call_duration = filters.get("min_duration")
    max_call_duration = filters.get("max_duration")
    if bx_wh_data.CALL_DURATION:
        if min_call_duration and bx_wh_data.CALL_DURATION < min_call_duration:
            logger.info(f"[-] Bitrix24: {domain}. Длительность звонка: {bx_wh_data.CALL_DURATION}, фильтр: {min_call_duration}")
            return False
        if max_call_duration and bx_wh_data.CALL_DURATION > max_call_duration:
            logger.info(f"[-] Bitrix24: {domain}. Длительность звонка: {bx_wh_data.CALL_DURATION}, фильтр: {max_call_duration}")
            return False

    passed_responsible_users_filters = check_responsible_users(domain, bx_wh_data, filters)
    if not passed_responsible_users_filters:
        return False

    # Проверка типа звонка
    allowed_call_types = filters.get('allowed_call_types')
    if allowed_call_types and not CallType.is_allowed_by_filters(bx_wh_data.CALL_TYPE, allowed_call_types):
        logger.info(f"[-] Bitrix24: {domain}. Тип звонка: {bx_wh_data.CALL_TYPE}, фильтр: {allowed_call_types}")
        return False

    bx24 = Bitrix24(webhook_url)

    call_info = get_bitrix_call_info(bx24, bx_wh_data.CALL_ID, webhook_url, body_str, api_router='/bitrix_webhook/v2')

    if crm_data and crm_data.get("get_deal_timeout"):
        get_deal_timeout = crm_data.get("get_deal_timeout")
    else:
        get_deal_timeout = 0
    time.sleep(get_deal_timeout)

    crm_entity_type = call_info['CRM_ENTITY_TYPE']  # CONTACT, LEAD, DEAL, COMPANY
    crm_entity_id = call_info['CRM_ENTITY_ID']

    if (crm_entity_type is not None
            and crm_entity_type not in [CRMEntityType.CONTACT,
                                        CRMEntityType.LEAD,
                                        CRMEntityType.DEAL,
                                        CRMEntityType.COMPANY]):
        logger.error(f"[!] Bitrix24: {domain}. Неизвестный тип сущности: {crm_entity_type}")
        return False

    # Фильтр по сущности CONTACT, LEAD, DEAL, COMPANY
    bitrix_entities_in: list = filters.get("bitrix_entities_in")
    if bitrix_entities_in and crm_entity_type not in bitrix_entities_in:
        logger.info(f"[-] Bitrix24: {domain}. Не прошли фильтр сущности. Сущность: {crm_entity_type}, фильтр: {bitrix_entities_in}")
        return False

    # Фильтр по первому звонку
    if filters.get("only_first_call"):
        if crm_entity_type is None:
            logger.info(f"[-] Bitrix24: {domain}. Фильтр невозможен для сущности {crm_entity_type}.")
            return False
        else:
            # Получаем список звонков сущности
            entity_calls = bx24.get_calls_by_entity(crm_entity_type, crm_entity_id, min_call_duration)
            # Проверка наличия первого звонка
            if len(entity_calls) == 0:
                logger.info(f"[-] Bitrix24: {domain}. У {crm_entity_type} {crm_entity_id} не найдено ни одного звонка")
                return False
            # Фильтрация по первому звонку
            first_call_with_min_duration_activity_id = int(entity_calls[0]["CRM_ACTIVITY_ID"])
            if first_call_with_min_duration_activity_id != bx_wh_data.CRM_ACTIVITY_ID:
                logger.info(f"[-] Bitrix24: {domain}. Не первый звонок у сущности {crm_entity_type}.")
                return False

    restricted_phones = filters.get('restricted_phones')
    if restricted_phones and phone_number_in_list(bx_wh_data.PHONE_NUMBER, restricted_phones):
        logger.info(f"[-] Bitrix24: {domain}. Установлен запрет на анализ телефона {bx_wh_data.PHONE_NUMBER}")
        return False

    entity, entity_deal = get_entity_and_entity_deal(bx24, crm_entity_type, crm_entity_id, bx_wh_data.CRM_ACTIVITY_ID)

    passed_pipelines_and_statuses_filters = check_pipelines_and_statuses(domain,
                                                                         filters,
                                                                         crm_entity_type,
                                                                         entity,
                                                                         entity_deal)
    if not passed_pipelines_and_statuses_filters:
        return False

    bx_data = bx24.get_bitrix_base_data(bx_wh_data, call_info)

    if Task.select().where(Task.file_url == bx_data['call_url']).exists():
        logger.info(f"[-] Bitrix24 {bx_wh_data.PORTAL_USER_ID}: Уже обрабатывали данный файл: {bx_data['call_url']}")
        return False

    # Фильтр по кастомным полям. Работает только со сделкой.
    custom_fields = filters.get('custom_fields', [])
    if crm_entity_type and custom_fields:
        # Сущность, в карточке которой ищем соответствующие поля.
        if entity_deal:
            entity_with_custom_fields = bx24.get_deal(entity_deal['ID'])
        elif crm_entity_type == CRMEntityType.DEAL or crm_entity_type == CRMEntityType.LEAD:
            entity_with_custom_fields = entity
        else:
            entity_with_custom_fields = None

        if entity_with_custom_fields:
            for field in custom_fields:
                # Если кастомного поля нет в карточке сущности, то фильтр не проходит.
                field_name = field['name']
                if field_name not in entity_with_custom_fields:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name} не найдено в сущности {crm_entity_type} {crm_entity_id}')
                    return False
                value = entity_with_custom_fields[field_name]

                value_in = field.get('value_in')
                if value_in and value not in value_in:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name}, со значением: "{value}", фильтр value_in: {value_in}')
                    return False

                value_not_in = field.get('value_not_in')
                if value_not_in and value in value_not_in:
                    logger.info(f'[-] Bitrix24: {domain}. '
                                f'Кастомное поле: {field_name}, со значением: "{value}", фильтр value_not_in: {value_not_in}')
                    return False

                logger.info(f'[+] Bitrix24: {domain}. Кастомное поле: {field_name}, со значением: "{value}"')

    return True
