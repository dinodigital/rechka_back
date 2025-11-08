import json
import random
import string
from typing import Optional

import peewee
from assemblyai import LemurTaskResponse, LemurQuestionResponse
from loguru import logger

from config import config as cfg
from data.models import Mode, User, Task, Payment, main_db, Report, RequestLog, ModeQuestion, ModeQuestionCalcType, \
    DefaultQuestions, Integration, ActiveTelegramReport, ModeQuestionType, IntegrationServiceName, ModeAnswer, Company
from modules.audiofile import Audiofile
from modules.json_processor.struct_checkers import get_dict_from_json


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


def create_task(
        duration_sec: int,
        file_url: str,
        report: Report,
        initial_duration: int = None,
) -> Task:
    """ Создает задачу анализа. """

    return Task.create(
        report=report,
        initial_duration=initial_duration,
        duration_sec=duration_sec,
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
    task.analyze_data = json.dumps(assembly.analyze_dict)
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
                             analyze_data: dict,
                             mode_questions):
    """ Обновляет задачу (analyze_data). """
    task.analyze_data = json.dumps(analyze_data)
    task.step = "analyzed"
    task.save()
    logger.debug(f"Обновлены данные анализа для задачи {task.id}.")

    logger.debug(f'Сохраняем ответы на вопросы от нейронной сети в базу данных. task_id={task.id}.')
    for question_id, answer_text in analyze_data.items():
        try:
            question = mode_questions.where(ModeQuestion.id == question_id).get()
        except peewee.DoesNotExist:
            logger.error(f'Не удалось найти в базе данных вопрос ID={question_id}. '
                         f'В ответе от нейронной сети он есть.')
            continue
        ModeAnswer.create(task=task, question=question, answer_text=answer_text)

    logger.debug(f'Формируем и сохраняем в базу данных ответы на системные колонки. task_id={task.id}.')
    custom_questions = task.report.get_custom_columns()
    for question in custom_questions:
        short_name = question.short_name
        try:
            func = DefaultQuestions.get_func(short_name)
        except ValueError:
            logger.error(f'Неизвестная вычисляемая колонка: {short_name}')
            continue
        answer_text = func(task)
        ModeAnswer.create(task=task, question=question, answer_text=answer_text)
    logger.info(f'Успешно сохранили ответы в БД. task_id={task.id}.')


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


def finish_task(task: Task):
    """ Обновляет задачу при возникновении ошибки. """
    task.status = Task.StatusChoices.DONE
    task.save()
    logger.debug(f"finish_task. task: {task.id}, status: {task.status}")


def not_enough_company_balance(company: Company, audio_duration_in_sec: int) -> bool:
    """
    Проверка, хватит ли баланса для проведения анализа.
    """
    current_balance = company.seconds_balance

    if current_balance < audio_duration_in_sec:
        logger.info(f"[-] Недостаточно баланса. "
                    f"Текущий баланс: {current_balance} сек. Необходимо: {audio_duration_in_sec} сек. "
                    f"company.id = {company.id}.")
        return True
    else:
        return False


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


class DBLogHandler:

    """
    Пишет сообщение в базу данных, если передан ID RequestLog.
    """

    def write(self, message):

        # Получаем объект, в который нужно сохранить сообщение.
        request_log_id = message.record.get('extra', {}).get('request_log_id')
        if request_log_id:
            request_log = RequestLog.get_or_none(id=request_log_id)
        else:
            request_log = None

        # Пишем в БД, если объект найден.
        if request_log:
            if request_log.log:
                request_log.log += '\n'
            request_log.log += message.record['message']
            request_log.save(only=['log'])


def create_default_telegram_report(
        user: User,
        sheet_id: Optional[str] = None,
):
    """
    Создает Telegram-интеграцию и базовый отчет к ней.
    """
    with main_db.atomic():
        # Создаем Telegram-интеграцию.
        i_data = {'access': {'telegram_ids': user.tg_id}}
        integration = Integration.create(
            user=user,
            company=user.company,
            service_name=IntegrationServiceName.TELEGRAM,
            account_id=f'telegram_{user.tg_id}',
            data=json.dumps(i_data),
        )
        logger.debug(f'Создал интеграцию: {integration.id}')

        # Создаем базовый отчет.
        default_full_json = get_dict_from_json(cfg.DEFAULT_JSON_PATH)
        report_context = default_full_json['params']['context']
        questions = default_full_json['params']['questions']

        report = Report.create(
            active=True,
            name='Базовый отчет',
            integration=integration,
            sheet_id=sheet_id,
            final_model=cfg.TASK_MODELS_LIST[-1],
            context=report_context,
        )
        logger.debug(f'Создал отчет: {report.id}')

        # Устанавливаем активный отчет в Telegram-боте.
        active_tg_report, created = ActiveTelegramReport.get_or_create(user=user, defaults={'report': report})
        if not created:
            active_tg_report.report = report
            active_tg_report.save(only=['report'])
        logger.debug(f'Выбрали в боте отчет {report.id}')

        default_mq_kwargs = {
            'is_active': True,
            'report': report,
        }
        # Создаем системные вопросы.
        column_index = 1
        for q_params in DefaultQuestions.question_functions.values():
            ModeQuestion.create(
                short_name=q_params['title'],
                calc_type=ModeQuestionCalcType.CUSTOM,
                column_index=column_index,
                question_text='',
                answer_type=q_params.get('answer_type', ModeQuestionType.STRING),
                **default_mq_kwargs,
            )
            column_index += 1
        logger.info(f'Создали системные колонки для отчета.')

        # Создаем AI колонки из базового json.
        for q_params in questions:
            ModeQuestion.create(
                short_name=q_params['short_name'],
                calc_type=ModeQuestionCalcType.AI,
                column_index=column_index,
                context=q_params['context'],
                question_text=q_params['question'],
                answer_type=q_params['answer_type'],
                answer_format=q_params['answer_format'],
                answer_options=q_params['answer_options'],
                **default_mq_kwargs,
            )
            column_index += 1
        logger.info(f'Создали json-колонки для отчета.')
