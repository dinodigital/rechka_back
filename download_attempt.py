import json
import time
from datetime import datetime, timedelta

import requests
from loguru import logger

from config.const import AmoNoteType
from data.models import CallDownload, CallDownloadAMO, Integration, IntegrationServiceName
from helpers.db_helpers import select_pg_stat_activity
from integrations.amo_crm.amo_api_core import AmoApi
from integrations.bitrix.bitrix_api import Bitrix24
from config import config
from integrations.bitrix.exceptions import DataIsNotReadyError


def download_file_from_bitrix(call_id, webhook):
    bx24 = Bitrix24(webhook)
    try:
        call_info = bx24.get_call_info(call_id)
    except DataIsNotReadyError as exc:
        logger.error(f'Перехват DataIsNotReadyError. Call ID: {call_id}. Exc: {exc}')
        call_info = None
    except IndexError as ie:
        logger.error(f'Перехват IndexError. Call ID: {call_id}. Exc: {ie}')
        call_info = None
    except Exception as e:
        logger.error(f'Перехват неизвестной ошибки. Call ID: {call_id}. Exc: {e}')
        call_info = None
    return call_info


def download_file_from_amo(entity_id, entity_name, account_id):
    integration: Integration = Integration.get_or_none(
        (Integration.account_id == account_id)
        & (Integration.service_name == IntegrationServiceName.AMOCRM)
    )
    if integration is None:
        logger.error(f"[-] AmoCRM attempt: Аккаунт с id {account_id} не найден. ")
        return None

    amo = AmoApi(integration)

    extra_params = {
        "filter[note_type]": f"{AmoNoteType.CALL_IN},{AmoNoteType.CALL_OUT}",
        "order[updated_at]": "desc"
    }

    notes = amo.get_entity_notes(entity_name=entity_name, entity_id=entity_id, extra_params=extra_params)

    notes = notes['_embedded']['notes'] if notes else []
    if not notes:
        return None

    notes = sorted(notes, key=lambda x: x['created_at'])

    logger.info(f"[-] Notes: {notes}")

    for note in notes:
        if note['note_type'] in [AmoNoteType.CALL_IN, AmoNoteType.CALL_OUT]:
            params = note['params']
            try:
                duration = int(params['duration'])
            except TypeError:
                duration = 0

            if duration > 0:
                return {
                    'call_url': params['link'],
                    'note_id': note['id']
                } if params['link'] else None


def update_downloads_bitrix():
    pending_downloads = CallDownload.select().where(
        (CallDownload.status != "completed") &
        (CallDownload.status != "rejected")
    )

    logger.info(f"Начинаю скачивать аудио Bitrix: всего {len(pending_downloads)}")

    # Проходимся по всем записям и пробуем их загрузить
    for record in pending_downloads:
        if record.timestamp < datetime.now() - timedelta(days=1):
            record.status = "rejected"
            record.save()
            logger.info(f"Запись с Call ID {record.call_id} отклонена из-за истечения срока.")
            continue
        call_info = download_file_from_bitrix(record.call_id, record.webhook)

        # Если загрузка успешна
        if call_info is not None:
            record.status = "completed"
        else:
            record.status = "failed"
            record.retry_count += 1

        # Обновляем поле last_attempt независимо от результата
        record.last_attempt = datetime.now()

        # Сохраняем обновленный статус и количество попыток
        record.save()
        logger.info(f"Call ID {record.call_id}: Status - {record.status}, Retry Count - {record.retry_count}, Call Info - {call_info}")

        if call_info:
            try:
                # parsed_data = json.loads(record.request_data)
                api_router = "/bitrix_webhook/v2" if record.api_router else "/bitrix_webhook"
                response = requests.post(f"{'https://api' if config.PRODUCTION else 'http://test'}.rechka.ai{api_router}",
                                         data=record.request_data)
                logger.info(f"Отправил запрос на обработку Bitrix - {response.text},"
                            f"Статус: {response.status_code}")
            except json.JSONDecodeError as e:
                logger.error(
                    f"Ошибка при декодировании JSON из record.request_data: {e}. Данные: {record.request_data}")


def update_downloads_amo():
    pending_amo_downloads = CallDownloadAMO.select().where(
        (CallDownloadAMO.status != "completed") &
        (CallDownloadAMO.status != "rejected")
    )

    logger.info(f"Начинаю скачивать аудио AMO: всего {len(pending_amo_downloads)}")

    # Проходимся по всем записям и пробуем их загрузить
    for record in pending_amo_downloads:
        if record.timestamp < datetime.now() - timedelta(days=1):
            record.status = "rejected"
            record.save()
            logger.info(f"Запись с Entity ID {record.entity_id} отклонена из-за истечения срока.")
            continue
        call_info = download_file_from_amo(entity_id=record.entity_id,
                                           entity_name=record.entity_name,
                                           account_id=record.account_id)

        logger.debug(f"Результаты download_file_from_amo return: {call_info}")

        # Если загрузка успешна
        if call_info is not None:
            record.status = "completed"
        else:
            record.status = "failed"
            record.retry_count += 1

        # Обновляем поле last_attempt независимо от результата
        record.last_attempt = datetime.now()

        # Сохраняем обновленный статус и количество попыток
        record.save()
        logger.info(f"Entity ID {record.entity_id}: Status - {record.status}, Retry Count - {record.retry_count}, Call Info - {call_info}")

        if call_info:
            try:
                response = requests.post(f"{'https://api' if config.PRODUCTION else 'http://test'}.rechka.ai{record.webhook}",
                                         headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                         data=record.request_data)
                logger.info(f"Отправил запрос на обработку AMO - {response.text},"
                            f"Статус: {response.status_code},"
                            f"Ссылка: {'https://api' if config.PRODUCTION else 'http://test'}.rechka.ai{record.webhook}"
                            )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Ошибка при декодировании JSON из record.request_data: {e}. Данные: {record.request_data}")


def main():
    while True:
        update_downloads_bitrix()
        update_downloads_amo()
        select_pg_stat_activity()
        logger.info("Ожидание 1 час перед следующей попыткой...")
        time.sleep(3600)  # 3600 секунд = 1 час


if __name__ == "__main__":
    main()
