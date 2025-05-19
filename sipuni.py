import csv as csv_lib
import json
import time
from io import StringIO
from json import JSONDecodeError

import requests
from loguru import logger
from requests import HTTPError
from retry import retry_call
from sipuni_api import Sipuni, SipuniException
from datetime import datetime, timedelta
# from celery import Celery
# from kombu import Queue

from config.config import REDIS_URL
from data.models import SipuniCall, Integration, IntegrationServiceName
from helpers.db_helpers import not_enough_balance, create_task
from misc.time import get_refresh_time
from modules.audio_processor import process_crm_call
from modules.audiofile import Audiofile


class SipuniFile(Sipuni):
    def _send_api_request(self, method: str, url: str, data: dict = {},
                          headers: dict = {}, csv=False, file=False) -> any:
        """
        :param method: str (get, post, put, delete, head)
        :param url: str
        :param data: dict
        :param headers: dict
        :param csv: bool (True in statistic)
        :param file: bool (True in record)
        :return: any
        """
        self._session.headers.update(headers)
        try:
            response = self._session.__getattribute__(method)(url=url, json=data)
            if response.status_code > 204:
                raise SipuniException(response.status_code, response.reason, response.text)
            if csv:
                return response.content.decode('utf-8')
            if file:
                return dict(content=response.content, headers=response.headers)
            return response.json()
        except (requests.ConnectionError, JSONDecodeError):
            raise SipuniException(500,
                                  'Server not answer or Cant decoded to json',
                                  'Server not answer or Cant decoded to json'
                                  )


# sipuni_calls_fetcher = Celery('sipuni_calls_fetcher', broker=REDIS_URL)
# sipuni_calls_fetcher.conf.task_queues = (
#     Queue('sipuni_calls_fetcher', routing_key='sipuni_calls_fetcher'),
# )
#
# sipuni_calls_fetcher.conf.beat_schedule = {
#     'every': {
#         'task': 'sipuni.sipuni_fetcher_task',
#         'schedule': 3600.0,
#     },
# }


def csv_parsing(csv_data: str):
    csv_file = StringIO(csv_data)
    return csv_lib.DictReader(csv_file, delimiter=';')


# @sipuni_calls_fetcher.task(queue='sipuni_calls_fetcher')
def sipuni_fetcher_task():
    sipuni_integrations = Integration.select().where(Integration.service_name == IntegrationServiceName.SIPUNI)

    for integration in sipuni_integrations:
        integration_client = integration.account_id
        token = json.loads(integration.data).get('access').get("application_token")
        client = SipuniFile(integration_client, token)

        latest_record = SipuniCall.select().where(SipuniCall.account_id == integration_client).order_by(SipuniCall.created.desc()).first()
        if latest_record:
            from_date = latest_record.created
        else:
            from_date = datetime.now() - timedelta(days=1)
        calls_raw = client.get_call_stats(from_date=from_date, to_date=datetime.now())
        calls = csv_parsing(calls_raw)

        for call in calls:
            created = call.get("Время")
            call_id = call.get("ID записи")

            call_type = call.get("\ufeffТип")
            call_responsible = call.get("Ответственный из CRM")

            tel_from = call.get("Откуда")
            tel_to = call.get("Куда")
            if tel_from == "202" or tel_to == "202":
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Запись от внутреннего номера сотрудника 202: {call_id}")
                continue

            i_data = integration.get_data()
            filters = i_data.get("filters")

            # Валидация направления звонка.
            allowed_call_types = filters.get('allowed_call_types')
            if allowed_call_types and call_type not in allowed_call_types:
                logger.info(f"[-] Sipuni - {call_id} - "
                            f"Направление звонка: {call_type}, фильтр: {allowed_call_types}")
                continue

            # Проверка ответственных
            responsible_users = filters.get('responsible_users')

            if responsible_users and call_type == 'Входящий' and int(tel_to) not in responsible_users:
                logger.info(f"[-] Sipuni {call_id} - {call_type} - "
                            f"Ответственный: {tel_to}, фильтр: {responsible_users}")
                continue

            if responsible_users and call_type == 'Исходящий' and int(tel_from) not in responsible_users:
                logger.info(f"[-] Sipuni {call_id} - {call_type} - "
                            f"Ответственный: {tel_from}, фильтр: {responsible_users}")
                continue

            sipuni_call = SipuniCall.get_or_none(
                call_id=call_id
            )
            if sipuni_call is not None:
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Запись уже обрабатывалась: {call_id}")
                continue

            created_time = datetime.strptime(call.get("Время"), '%d.%m.%Y %H:%M:%S')
            SipuniCall.create(
                call_id=call.get("ID записи"),
                account_id=integration_client,
                created=created_time
            )

            try:
                record = retry_call(
                    client.get_record, fargs=[call_id],
                    tries=3, delay=3, backoff=4, logger=logger,
                )
            except SipuniException as ex:
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Не удалось получить запись звонка: {call_id}. {ex}")
                continue

            try:
                decoded_record = record.get("content").decode('utf-8')
            except UnicodeDecodeError:
                decoded_record = ''

            # Сравниваем
            if decoded_record == 'Record was not found':
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Запись не найдена: {call_id}")
                continue
            elif decoded_record == 'Call not found':
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Звонок не найден: {call_id}")
                continue
            else:
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Обработка записи: {call_id}")

            try:
                audio: Audiofile = Audiofile().load_from_sipuni(record.get("content"), record.get("headers"))
            except HTTPError:
                logger.error(f"[-] Sipuni: {integration_client}. "
                             f"Не удалось скачать аудиофайл: {call_id}")
                continue

            min_call_duration = filters.get("min_duration")
            max_call_duration = filters.get("max_duration")

            if not_enough_balance(integration.user, audio.duration_in_sec):
                current_balance = integration.user.get_payer_balance()
                logger.info(f"[-] Sipuni: {integration_client}. "
                            f"Недостаточно баланса {current_balance}. Необходимо: {audio.duration_in_sec}")
                continue

            if (
                    min_call_duration and audio.duration_in_sec < min_call_duration
                    or
                    max_call_duration and audio.duration_in_sec > max_call_duration
            ):
                logger.info(
                    f"[-] Sipuni: {integration_client}. Фактическая длительность звонка: {audio.duration_in_sec}, фильтр: {min_call_duration}-{max_call_duration}")
                continue

            if call_type == 'Входящий':
                call_responsible = tel_to
            elif call_type == 'Исходящий':
                call_responsible = tel_from

            task = create_task(user=integration.user,
                               initial_duration=audio.duration_in_sec,
                               duration_sec=audio.duration_in_sec,
                               file_url=audio.url)
            logger.info(f"Создал новый Sipuni Task {task.id}")

            # Генерация ячеек для Google таблицы
            basic_data = [get_refresh_time(),
                          created,
                          audio.duration_min_sec,
                          call_responsible,
                          call_type]

            process_crm_call(audio, integration.user, basic_data, task)


def main():
    while True:
        logger.info("Начинаю обработку...")
        sipuni_fetcher_task()
        logger.info("Ожидание 5 мин перед следующей попыткой...")
        time.sleep(300)  # 3600 секунд = 1 час


if __name__ == "__main__":
    main()

