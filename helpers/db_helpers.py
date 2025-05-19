import json
import random
import string
from typing import Optional

import peewee
from assemblyai import LemurTaskResponse, LemurQuestionResponse
from loguru import logger

from config import config as cfg
from data.models import Mode, User, Task, Payment, main_db, Transaction
from integrations.gs_api.sheets import create_google_sheet_link
from modules.audiofile import Audiofile


def generate_unique_mode_id(length: int = 12) -> str:
    """
    Генерация уникального mode_id, которого нет в БД
    """
    # Все доступные символы: большие и маленькие буквы, цифры
    all_characters = string.ascii_letters + string.digits

    while True:
        mode_id = ''.join(random.choice(all_characters) for _ in range(length))
        if not Mode.get_or_none(mode_id=mode_id):
            return mode_id


def create_db_task(db_user: User, assembly, audio: Audiofile) -> Task:
    """
    Создает сущность Task в базе данных
    """
    db_task: Task = Task.create(
        user=db_user,
        transcript_id=assembly.transcript.id,
        duration_sec=audio.duration_in_sec,
        analyze_id=assembly.lemur_response.request_id,
        analyze_data=json.dumps(assembly.analyze_list),
        file_url=audio.url
    )

    logger.info(f"Создал в БД новый Task, id:{db_task.id}")

    return db_task


def create_task(user: User, duration_sec: int, file_url: str, initial_duration: int = None) -> Task:
    """ Создает задачу анализа. """
    return Task.create(
        user=user,
        initial_duration=initial_duration,
        duration_sec=duration_sec,
        calculated_duration=duration_sec,
        status=Task.StatusChoices.IN_PROGRESS,
        file_url=file_url,
        step="passed_filters"
    )


def update_task_after_analysis(task: Task,
                               assembly,
                               audio: Audiofile):
    """ Обновляет задачу после завершения анализа. """
    task.assembly_duration = assembly.transcript.audio_duration
    task.transcript_id = assembly.transcript.id
    task.analyze_id = assembly.lemur_response.request_id
    task.analyze_data = json.dumps(assembly.analyze_list)
    task.file_url = audio.url
    task.save()
    logger.debug(f"Задача {task.id} успешно обновлена после анализа {task.analyze_id}.")


def update_task_after_analysis_short(task: Task,
                                     analyze_data: str,
                                     analyze_id: str,
                                     input_tokens: int = None,
                                     output_tokens: int = None):
    """ Обновляет задачу после завершения транскрибации. """
    task.analyze_id = analyze_id
    task.analyze_data = analyze_data
    task.analyze_input_tokens = input_tokens
    task.analyze_output_tokens = output_tokens
    task.save()


def update_task_lemur_response(task: Task,
                               lemur_response: LemurTaskResponse | LemurQuestionResponse):
    """ Обновляет задачу (lemur_response). """
    task.analyze_id = lemur_response.request_id
    task.analyze_input_tokens = lemur_response.usage.input_tokens
    task.analyze_output_tokens = lemur_response.usage.output_tokens
    task.save()
    logger.debug(f"update_task_lemur_response. task: {task.id}, analyze_id: {task.analyze_id}, "
                 f"analyze_input_tokens: {task.analyze_input_tokens}, "
                 f"analyze_output_tokens: {task.analyze_output_tokens}")


def update_task_analyze_data(task: Task,
                             analyze_data: str):
    """ Обновляет задачу (analyze_data). """
    task.analyze_data = analyze_data
    task.step = "analyzed"
    task.save()
    logger.debug(f"Обновлены данные анализа для задачи {task.id}.")


def update_task_after_transcript(task: Task,
                                 assembly_duration: int,
                                 transcript_id: str):
    """ Обновляет задачу после завершения транскрибации. """
    task.assembly_duration = assembly_duration
    task.transcript_id = transcript_id
    task.step = "transcribed"
    task.save()
    logger.debug(f"update_task_after_transcript. task: {task.id}, assembly_duration: {task.assembly_duration}, "
                 f"transcript_id: {task.transcript_id}")


def update_task_with_error(
        task: Task,
        error: Optional[str] = None,
        ex: Optional[Exception] = None,
) -> None:
    """
        Переводит задачу в статус «Ошибка» и сохраняет текст ошибки в БД и в лог.
        Если передан аргумент `ex`, то в лог еще пишутся тип и текст исключения.
    """
    task.status = Task.StatusChoices.ERROR
    if error is not None:
        logger.error(f'Ошибка: {error}. Задача: {task.id}.' + f' {type(ex)} {ex}.' if ex else '')
        task.error_details = error
    task.save()


def update_task_with_google_error(task: Task, uploaded_data: list, mode: Mode = None, error=None):
    """ Обновляет задачу при возникновении ошибки google. """
    task.status = Task.StatusChoices.IN_PROGRESS
    if error is not None:
        try:
            task.step = 'uploaded_error'
            task.error_details = str(error)
            task.uploaded_data = json.dumps(uploaded_data)
            task.mode = mode
        except Exception as e:
            logger.error(f"Ошибка при обновлении task.error_details (google) {task.id}, <{type(e)}> {e}")
    task.save()


def finish_task(task: Task):
    """ Обновляет задачу при возникновении ошибки. """
    task.status = Task.StatusChoices.DONE
    task.save()
    logger.debug(f"finish_task. task: {task.id}, status: {task.status}")


def not_enough_balance(user: User, audio_duration_in_sec: int) -> bool:
    """
    Проверка, хватит ли баланса для проведения анализа.
    """
    current_balance = user.get_payer_balance()
    return current_balance < audio_duration_in_sec
    # current_balance = calculate_balance(user)
    # return current_balance < (audio_duration_in_sec / 60)


def calculate_balance(user: User) -> int:
    """ Рассчитывает текущий баланс пользователя. """
    total_minutes_added = (
        Transaction
        .select(peewee.fn.SUM(Transaction.minutes))
        .where(
            Transaction.user == user,
            Transaction.payment_type == 'balance'
        )
        .scalar() or 0
    )

    total_minutes_used = (
        Task
        .select(peewee.fn.SUM(Task.assembly_duration))
        .where(Task.user == user, Task.status == Task.StatusChoices.DONE)
        .scalar() or 0
    )

    return total_minutes_added - total_minutes_used


def create_payment(db_user: User, invoice_sum: int, minutes_to_buy: int) -> Payment:
    """
    Создать платеж в БД
    """
    seconds_to_buy = minutes_to_buy * 60

    payment: Payment = Payment.create(
        user=db_user,
        invoice_sum=invoice_sum,
        minutes=minutes_to_buy,
        seconds=seconds_to_buy,
        ppm_in_rub=cfg.PRICE_PER_MINUTE_IN_RUB,
        ppm_in_usd=cfg.PRICE_PER_MINUTE_IN_USD
    )

    logger.info(f"Создал в БД платеж. tg_id: {db_user.tg_id}, invoice_sum: {invoice_sum}")

    return payment


def create_mode_from_json(full_json: dict, sheet_id, mode_id=None) -> Mode:
    # Создание нового Mode в БД

    def remove_short_names_from_params(params) -> dict:
        """
        Удаляет все short_name из params
        """
        # Удаляем ключ 'short_name' из каждого элемента списка
        for item in params['questions']:
            item.pop('short_name', None)

        return params

    if not mode_id:
        mode_id = generate_unique_mode_id()
        tg_link = cfg.BOT_LINK + f"?start=activate_{mode_id}"
    else:
        tg_link = cfg.BOT_LINK

    return Mode.create(
        name=full_json['mode_name'],
        mode_id=mode_id,
        full_json=json.dumps(full_json),
        params=json.dumps(remove_short_names_from_params(full_json['params'])),
        sheet_id=sheet_id,
        sheet_url=create_google_sheet_link(sheet_id),
        insert_row=full_json['row'],
        tg_link=tg_link
    )


def select_db_1() -> bool:
    try:
        with main_db:
            cursor = main_db.execute_sql("SELECT 1;")
            result = cursor.fetchone()
            return True if result[0] else False
    except Exception as e:
        logger.error(f"Ошибка соединения с БД при выполнении запроса SELECT: {e}")
    return False


def select_pg_stat_activity() -> None:
    try:
        with main_db:
            cursor = main_db.execute_sql("SELECT COUNT(*) FROM pg_stat_activity WHERE usename='mrcrab';")
            result = cursor.fetchone()
            logger.info(f"pg_stat_activity: {result[0]}")
    except Exception as e:
        logger.error(f"Ошибка соединения с БД при выполнении запроса SELECT pg_stat_activity: {e}")
