import sys
sys.path.append('/root/speechka/')

import time
from datetime import datetime, timedelta
from typing import Optional

from beeline_portal import BeelinePBX
from beeline_portal.models import CallRecord
from loguru import logger

from data.models import Integration, IntegrationServiceName, User
from helpers.db_helpers import not_enough_balance
from integrations.beeline.models import Direction
from misc.time import get_refresh_time
from modules.audio_processor import process_crm_call
from modules.audiofile import Audiofile
from modules.numbers_matcher import phone_number_in_list


def make_basic_data(call: CallRecord) -> list:
    """
    Создание ячеек для Google таблицы:
    1. Дата и время обработки звонка.
    2. Дата и время звонка.
    3. Продолжительность звонка (в секундах).
    4. Фамилия ответственного (и имя, если есть).
    5. Направление вызова (входящий, исходящий).
    """
    refresh_time = get_refresh_time()
    call_date = call.date.strftime('%Y-%d-%m %H:%M')
    duration_sec = call.duration // 1000
    responsible_user_name = call.abonent.last_name

    if call.abonent.first_name:
        responsible_user_name = f'{call.abonent.first_name} {responsible_user_name}'

    direction = Direction.get_rus(call.direction)

    result = [refresh_time, call_date, duration_sec, responsible_user_name, direction]

    return result


def check_call_filters(call: CallRecord, filters: dict):
    """
    Проверка фильтров:
    1. Ненулевой длительности звонка.
    2. Минимальной длительности звонка.
    3. Максимальной длительности звонка.
    4. Ответственных.
    5. Запрещенных номеров.
    6. Типа звонка (входящий, исходящий).
    7. Только первого звонка.

    True – проверка всех фильтров пройдена успешно.
    False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
    """

    # Валидация длительности звонка
    if call.duration == 0:
        logger.info(f'[-] Билайн – Звонок не состоялся. Duration: 0')
        return False

    # Билайн отдает длительность звонка в миллисекундах.
    call_duration_sec = call.duration // 1000

    # Проверка минимальной длительности звонка
    min_duration = filters.get('min_duration')
    if min_duration and call_duration_sec < min_duration:
        logger.info(f'[-] Билайн – Не проходим по мин. длительности. Факт. длит.: {call_duration_sec}, мин: {min_duration}')
        return False

    # Проверка максимальной длительности звонка
    max_duration = filters.get('max_duration')
    if max_duration and call_duration_sec > max_duration:
        logger.info(f'[-] Билайн – Не проходим по макс. длительности. Факт. длит.: {call_duration_sec}, макс: {max_duration}')
        return False

    # Проверка ответственных
    responsible_phones = filters.get('responsible_phones')
    if responsible_phones and not phone_number_in_list(call.abonent.phone, responsible_phones):
        logger.info(f'[-] Билайн – Ответственный: {call.abonent.phone}, фильтр: {responsible_phones}')
        return False

    # Проверка на запрет на анализ телефонных номеров
    restricted_phones = filters.get('restricted_phones')
    if restricted_phones and phone_number_in_list(call.phone, restricted_phones):
        logger.info(f'[-] Билайн – Установлен запрет на анализ телефона {call.phone}')
        return False

    allowed_call_types = filters.get('allowed_call_types')
    if allowed_call_types and not Direction.is_allowed_by_filters(call.direction, allowed_call_types):
        logger.info(f'[-] Билайн – Тип звонка: {call.direction}. Фильтр: {allowed_call_types}')
        return False

    return True


def process_call(call: CallRecord, filters: dict, client, user: User):
    filters_succeed = check_call_filters(call, filters)
    if not filters_succeed:
        return None

    # Скачивание аудиофайла
    logger.info('Загружаем звонок.')
    call_url = client.get_record_link(call.id_)['url']
    audio = Audiofile().load_from_url(call_url, name=f'beeline_{call.id_}')

    logger.info('Проверяем баланс.')
    # Проверка баланса по фактической длине аудиозаписи.
    if not_enough_balance(user, audio.duration_in_sec):
        logger.info(f"[-] Билайн – "
                    f"Недостаточно баланса {user.seconds_balance}. Необходимо: {audio.duration_in_sec}")
        return None

    logger.info('Проверяем длительность звонка.')
    # Вторичная проверка длительности звонка
    min_duration = filters.get('min_duration')
    max_duration = filters.get('max_duration')
    if (
               min_duration and audio.duration_in_sec < min_duration
            or max_duration and audio.duration_in_sec > max_duration
    ):
        logger.info(f'[-] Билайн – Не проходим по реальной длительности. '
                    f'Факт. длит.: {audio.duration_in_sec}, фильтр: {min_duration}-{max_duration}')
        return None

    # Анализ аудиозаписи и выгрузка отчета
    logger.info('Получаем basic_data')
    basic_data = make_basic_data(call)
    logger.info('Пишем в отчет')
    process_crm_call(audio, user, basic_data)
    logger.info('Обработали звонок')

def process_account_id(
        account_id: str,
        params: dict,
        processed: dict,
        process_on_first_run: bool = False,
) -> Optional[int]:

    logger.info(f'Обрабатываем интеграцию {account_id}')

    new_processed_count = 0
    if account_id not in processed:
        processed[account_id] = {}
        is_first_run = True
    else:
        is_first_run = False

    integration = Integration.get_or_none(account_id=account_id, service_name=IntegrationServiceName.BEELINE)
    if integration is None:
        logger.error('Интеграция не найдена.')
        return None

    filters = integration.get_filters()
    token = integration.get_decrypted_access_field('token')

    client = BeelinePBX(token)
    try:
        calls = list(client.get_records(params=params))
    except Exception as ex:
        logger.error(ex)
        response = client._send_api_request('get', 'records', params=params)
        logger.error(response)
        return None
    else:
        for call in calls:
            if call.id_ not in processed[account_id]:
                try:
                    if is_first_run and not process_on_first_run:
                        pass
                    else:
                        process_call(call, filters, client, integration.user)
                except Exception as ex:
                    logger.error(ex)
                finally:
                    processed[account_id][call.id_] = None
                    new_processed_count += 1

    return new_processed_count


def main():
    account_ids = ['president']
    # {'account_id': {
    #     'processed_call_1_id': None,
    #     'processed_call_2_id': None,
    #     'processed_call_3_id': None,
    #   }, ...
    # }
    processed = {}

    logger.info('Билайн – Запустили обработку.')
    while True:
        date_from = (datetime.now().astimezone().replace(microsecond=0) - timedelta(hours=12)).isoformat()
        params = {'dateFrom': date_from}
        logger.info(f'Билайн – обрабатываем звонки с {date_from}')

        for account_id in account_ids:
            new_processed_count = process_account_id(account_id, params, processed, process_on_first_run=True)
            if new_processed_count is None:
                logger.info(f'Билайн {account_id} – Не удалось обработать звонки.')
            else:
                logger.info(f'Билайн {account_id} – Обработали новых звонков: {new_processed_count}.')

        time.sleep(600)


if __name__ == '__main__':
    main()