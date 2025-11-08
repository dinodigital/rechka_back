import time
import urllib.parse
from datetime import datetime
from typing import Optional

from loguru import logger
from requests import HTTPError
from starlette.datastructures import FormData

from config.const import AmoNoteTypeID
from data.models import Integration, IntegrationServiceName, Task, CallDownloadAMO, Report, RequestLog
from data.server_models import LeadNoteAmoWebhook, ContactNoteAmoWebhook, BaseNoteAmoWebhook, make_note_webhook
from helpers.db_helpers import not_enough_company_balance, create_task
from helpers.integration_helpers import get_number_from_integration_settings
from integrations.amo_crm.amo_api_core import AmoApi
from misc.time import get_refresh_time
from modules.audio_processor import process_crm_call
from modules.audiofile import Audiofile


def get_lookup_entities(
        amo: AmoApi,
        lookup_entity_types: set,
        lead_id: int,
) -> dict:
    """
    Получает необходимые сущности для выгрузки дополнительных полей в отчет.
    """

    # Лид понадобится:
    # 1) если ищем поле в сущности лида;
    # 2) если ищем поле в сущности контакта и пришел вебхук лида.
    lead_with_contacts = 'CONTACT' in lookup_entity_types
    lead_entity = amo.get_lead_by_id(lead_id, with_contacts=lead_with_contacts)

    # Контакт понадобится:
    # 1) если ищем поле в сущности контакта;
    contact_entity = None
    if 'CONTACT' in lookup_entity_types:
        embedded_contacts = lead_entity['_embedded'].get('contacts')
        if embedded_contacts:
            contact_id = sorted(embedded_contacts, key=lambda x: x['is_main'], reverse=True)[0]['id']
            contact_entity = amo.get_contact_by_id(contact_id)

    # Компания понадобится:
    # 1) если ищем поле в сущности компании;
    company_entity = None
    if 'COMPANY' in lookup_entity_types:
        embedded_companies = lead_entity['_embedded'].get('companies')
        if embedded_companies:
            company_id = embedded_companies[0]['id']
            company_entity = amo.get_company_by_id(company_id)

    entities = {
        'LEAD': lead_entity,
        'CONTACT': contact_entity,
        'COMPANY': company_entity,
    }
    return entities


def make_crm_values_to_upload(
        amo: AmoApi,
        webhook: BaseNoteAmoWebhook,
        duration_min_sec: str,
        add_pipeline_and_status_names: bool,
        settings: dict,
        crm_data: Optional[dict] = None,
) -> list:
    """
    Создание ячеек для Google таблицы
    """
    refresh_time = get_refresh_time()
    call_date = webhook.date_create
    responsible_user_name = amo.get_responsible_user_name(webhook.main_user_id)

    # Формируем ссылку на страницу сделки в AmoCRM.
    if isinstance(webhook, ContactNoteAmoWebhook):
        entity_link = amo.make_contact_link(webhook.element_id)
        number = get_number_from_integration_settings(settings)
        amocrm_link = amo.get_lead_link_by_contact_id(webhook.element_id, number=number)
        lead_id = amocrm_link.split("/")[-1]
    elif isinstance(webhook, LeadNoteAmoWebhook):
        entity_link = amo.make_lead_link(webhook.element_id)
        amocrm_link = entity_link
        lead_id = webhook.element_id
    else:
        entity_link = ""
        amocrm_link = ""
        lead_id = 0

    basic_data_full = [
        {'crm_id': 'refresh_time', 'value': refresh_time},
        {'crm_id': 'call_date', 'value': call_date},
        {'crm_id': 'duration_min_sec', 'value': duration_min_sec},
        {'crm_id': 'responsible_user_name', 'value': responsible_user_name},
        {'crm_id': 'deal_url', 'value': amocrm_link},
    ]

    if add_pipeline_and_status_names:
        # Получаем названия воронки и статуса

        if not lead_id:
            pipline_name = ""
            status_name = ""
        elif lead_id == "У контакта нет связанных сделок":
            pipline_name = "У контакта нет связанных сделок"
            status_name = "У контакта нет связанных сделок"
        else:
            pipline_name, status_name = amo.get_pipeline_and_status_names(lead_id)

        basic_data_full.extend([
            {'crm_id': 'pipeline', 'value': pipline_name},
            {'crm_id': 'stage', 'value': status_name},
        ])

    if crm_data:
        crm_system_fields = crm_data.get('system_fields')
        if crm_system_fields:

            # Выгрузка ссылки на сущность, к которой привязан звонок.
            if 'entity_link' in crm_system_fields:
                basic_data_full.append({
                    'crm_id': 'entity_link',
                    'value': entity_link,
                })

            # Выгрузка номера телефона в отчет.
            if 'phone_number' in crm_system_fields:
                basic_data_full.append({
                    'crm_id': 'phone_number',
                    'value': webhook.PHONE.lstrip('+'),
                })

            # Выгрузка типа звонка в отчет.
            if 'call_type' in crm_system_fields:
                note_type_name = AmoNoteTypeID(webhook.note_type).name
                basic_data_full.append({
                    'crm_id': 'call_type',
                    'value': note_type_name,
                })

            # Выгрузка порядкового номера звонка в отчет.
            if 'index_number' in crm_system_fields:
                all_calls = amo.get_all_calls_by_entity(webhook.entity, webhook.element_id)
                basic_data_full.append({
                    'crm_id': 'index_number',
                    'value': len(all_calls),
                })

        crm_fields = crm_data.get('crm_fields')
        if crm_fields:

            lookup_entity_types = set(field['crm_entity_type'] for field in crm_fields)
            lookup_entities = get_lookup_entities(amo, lookup_entity_types, lead_id)

            for field in crm_fields:
                lookup_entity = lookup_entities.get(field['crm_entity_type'])

                if lookup_entity is None:
                    logger.warning(f'[-] AmoCRM: {webhook.account_subdomain}. '
                                   f'Не найдена нужная сущность: {field["crm_entity_type"]}')
                    field_value = ''
                else:
                    field_id = field['crm_field_id']

                    if field_id in lookup_entity:
                        # Поле найдено в списке основных полей объекта.
                        field_value = lookup_entity[field_id] or ''
                    else:
                        # Ищем поле среди пользовательских полей объекта.
                        field_value = None
                        for custom_field in lookup_entity.get('custom_fields_values', []):
                            if str(custom_field['field_id']) == str(field_id):
                                field_value = ', '.join(x['value'] for x in custom_field.get('values', []))
                                break

                        if field_value is None:
                            logger.warning(f'[-] AmoCRM: {webhook.account_subdomain}. '
                                           f'CRM поле: {field_id} не найдено в сущности {lookup_entity}')
                            field_value = ''

                basic_data_full.append({
                    'crm_entity_type': field['crm_entity_type'],
                    'crm_id': field['crm_field_id'],
                    'value': field_value,
                })

    return basic_data_full


def process_amo_webhook(
        form_data: FormData,
        add_pipeline_and_status_names: bool,
        use_reports: bool = False,
        context_id: Optional[str] = None,
):
    """
    Обработчик вебхука AMOCRM.

    Аргументы:
    :param form_data: данные, полученные от AmoCRM.
    :param add_pipeline_and_status_names: флаг «добавить к ответу поля «Название канала» и «Название статуса».
    :param use_reports: использовать модель Report (отчет) для фильтрации и обработки звонка.
    :param context_id:

    Обрабатывает следующие типы списков:
    1. Сделки.
    2. Контакты.
    """
    logger.debug(f"[-] AmoCRM: form_data {form_data}.")
    webhook = make_note_webhook(form_data)
    logger.debug(f"[-] AmoCRM: webhook {webhook}.")
    if webhook is None:
        logger.info(f"[-] AmoCRM: Неизвестный тип вебхука: {form_data}")
        return None

    if webhook.note_type not in [AmoNoteTypeID.CALL_IN, AmoNoteTypeID.CALL_OUT]:
        try:
            note_type_name = AmoNoteTypeID(webhook.note_type).name
        except ValueError:
            note_type_name = 'Неизвестный тип'
        logger.info(f"[-] Вебхук AmoCRM - {webhook.account_subdomain} - "
                    f"Не звонок. Note_type: {webhook.note_type} ({note_type_name})")
        return False

    if use_reports:
        request_path = '/amo_webhook/v2_report'
    else:
        if add_pipeline_and_status_names:
            request_path = '/amo_webhook/v2'
        else:
            request_path = '/amo_webhook'
    request_log = RequestLog.create(
        context_id=context_id,
        method='POST',
        path=request_path,
        headers='',
        body=str(form_data),
    )
    request_log_id = request_log.id

    if not webhook.DURATION:
        logger.info(f"[-] AmoCRM: Аккаунт с id {webhook.account_id} имеет DURATION = {webhook.DURATION}. Субдомен: {webhook.account_subdomain}", request_log_id=request_log_id)
        return None

    # Валидация интеграции
    integration: Integration = Integration.get_or_none(
        (Integration.account_id == webhook.account_id)
        & (Integration.service_name == IntegrationServiceName.AMOCRM)
    )
    if integration is None:
        logger.info(f"[-] AmoCRM: Аккаунт с id {webhook.account_id} не найден. Субдомен: {webhook.account_subdomain}", request_log_id=request_log_id)
        return None

    # Связываем запрос с компанией.
    request_log.company = integration.company
    request_log.save(only=['company'])

    # Проверяем, что еще не обрабатывали данный аудиофайл.
    if Task.select().where(Task.file_url == webhook.LINK).exists():
        logger.info(f"[-] AmoCRM {webhook.account_subdomain}: Уже обрабатывали данный файл: {webhook.LINK}", request_log_id=request_log_id)
        if webhook.LINK is None:
            CallDownloadAMO.create_or_update_from_webhook(webhook, form_data, add_pipeline_and_status_names)
        return None

    i_data = integration.get_data()
    amo = AmoApi(integration)

    if use_reports:
        reports = Report.select().where(
            (Report.integration == integration) & (Report.active == True)
        )
        if reports.count() == 0:
            logger.info(f'[-] AmoCRM {webhook.account_subdomain}: Нет активных отчетов.', request_log_id=request_log_id)
            return None

        # Оставляем отчеты, прошедшие фильтры.
        reports_bypass_filters = []
        for report in reports:
            filters = report.get_report_filters()
            settings = report.get_report_settings()
            crm_data = report.get_report_crm_data()

            if crm_data:
                # Задержка перед первым выполнением запросов к CRM.
                get_deal_timeout = crm_data.get('get_deal_timeout')
                if get_deal_timeout:
                    time.sleep(get_deal_timeout)

            if amo.check_call_filters(webhook, filters, settings):
                reports_bypass_filters.append(report)
            else:
                logger.info(f'[-] AmoCRM {webhook.account_subdomain}: Отчет ID={report.id} не прошел фильтры.')

        if not reports_bypass_filters:
            logger.info(f'[-] AmoCRM {webhook.account_subdomain}: Нет отчётов, прошедших фильтры.', request_log_id=request_log_id)
            return None

        highest_priority_report = min(reports_bypass_filters, key=lambda x: x.priority)
        logger.info(f'AmoCRM {webhook.account_subdomain}: '
                    f'Выбрали отчет ID={highest_priority_report.id} '
                    f'из {len(reports_bypass_filters)} отчетов: {", ".join(str(x.id) for x in reports_bypass_filters)}.')

        filters = highest_priority_report.get_report_filters()
        settings = highest_priority_report.get_report_settings()
        crm_data = highest_priority_report.get_report_crm_data()
        report = highest_priority_report
    else:
        filters = i_data.get('filters', {})
        settings = i_data.get('settings')
        crm_data = i_data.get('crm_data')
        report = None

        if crm_data:
            # Задержка перед первым выполнением запросов к CRM.
            get_deal_timeout = crm_data.get('get_deal_timeout')
            if get_deal_timeout:
                time.sleep(get_deal_timeout)

        filters_succeed = amo.check_call_filters(webhook, filters, settings, request_log_id=request_log_id)
        if not filters_succeed:
            return None

    # Скачивание аудиофайла
    try:
        if settings and settings.get('ats_type') == 'a1.by':
            a1_company_id = i_data['access']['company_id']
            a1_api_key = integration.get_decrypted_access_field('api_key')
            audio = Audiofile().load_from_a1(webhook.LINK, a1_company_id, a1_api_key, name=webhook.UNIQ)
        else:
            audio = Audiofile().load_from_url(webhook.LINK, name=webhook.UNIQ)
    except HTTPError as e:
        logger.error(f"[-] AmoCRM {webhook.account_subdomain}: "
                     f"Не удалось скачать аудиофайл: {webhook.LINK} "
                     f"Ошибка: <{type(e)}> {e}", request_log_id=request_log_id)
        results = CallDownloadAMO.select().where(CallDownloadAMO.entity_id == webhook.element_id,
                                                 CallDownloadAMO.date_create == webhook.date_create).limit(1)
        call_download = results[0] if len(results) > 0 else None
        if call_download is None:
            form_dict = dict(form_data)
            body_str = urllib.parse.urlencode(form_dict, doseq=True)
            call_download = CallDownloadAMO.create(
                account_id=webhook.account_id,
                entity_id=webhook.element_id,
                entity_name=webhook.entity,
                webhook="/amo_webhook/v2" if add_pipeline_and_status_names else "/amo_webhook",
                request_data=body_str,
                date_create=webhook.date_create
            )
        else:
            call_download.retry_count = call_download.retry_count + 1
            call_download.last_attempt = datetime.now()
            call_download.status = "failed"

        call_download.save()

        logger.warning(
            f'Звонок еще не загрузился в AMO. Задание на скачивание сохранено в БД. Entity ID: {webhook.element_id}', request_log_id=request_log_id)
        return None

    # Проверка баланса по фактической длине аудиозаписи.
    if not_enough_company_balance(integration.company, audio.duration_in_sec):
        return None

    # Вторичная проверка длительности звонка
    min_call_duration = filters.get("min_duration")
    max_call_duration = filters.get("max_duration")
    if (
            min_call_duration and audio.duration_in_sec < min_call_duration
            or
            max_call_duration and audio.duration_in_sec > max_call_duration
    ):
        return logger.info(
            f"[-] AmoCRM {webhook.account_subdomain}: Не проходим по реальной длительности. Факт. длит.: {audio.duration_in_sec}, фильтр: {min_call_duration}-{max_call_duration}", request_log_id=request_log_id)

    task = create_task(audio.duration_in_sec,
                       audio.url,
                       report,
                       initial_duration=webhook.DURATION)
    logger.info(f"Создал новый AMO Task {task.id}")

    task.request_log = request_log
    task.save(only=['request_log'])
    logger.info(f'Связал Task с RequestLog {request_log_id}.')

    # Генерация ячеек для Google таблицы
    crm_values_to_upload = make_crm_values_to_upload(amo,
                                                     webhook,
                                                     audio.duration_min_sec,
                                                     add_pipeline_and_status_names=add_pipeline_and_status_names,
                                                     settings=settings,
                                                     crm_data=crm_data)

    # Анализ аудиозаписи и выгрузка отчета
    string_report = process_crm_call(audio, integration.company, crm_values_to_upload, task)

    if filters.get("write_note"):
        logger.info(f'Выгрузка комментария в CRM в сущность {webhook.entity} entity_id={webhook.element_id}.')
        amo.add_note(webhook.element_id, string_report, webhook.entity)
        logger.info('Комментарий в CRM успешно выгружен.')
    else:
        logger.info('Выгрузка комментария в CRM отключена.')

    return None


def process_amo_webhook_v1(form_data, **kwargs):
    """
    Обработчик вебхука AMOCRM v1
    """
    process_amo_webhook(form_data, add_pipeline_and_status_names=False, **kwargs)


def process_amo_webhook_v2_report(form_data, **kwargs):
    """
    Обработчик вебхука AMOCRM v2 с отчетами `Report`.
    """
    process_amo_webhook(form_data, add_pipeline_and_status_names=True, use_reports=True, **kwargs)
