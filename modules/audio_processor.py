import json
import re
from json import JSONDecodeError
from typing import Optional, List

from assemblyai import LemurError
from pyrogram import Client
from pyrogram.types import Message
from retry import retry_call
from loguru import logger

from data.models import User, Task, GSpreadTask, Report, ModeAnswer, ModeQuestion, ModeQuestionCalcType, Company
from misc.time import get_refresh_time
from modules.audiofile import Audiofile
from helpers.db_helpers import not_enough_company_balance, update_task_after_analysis, update_task_with_error, \
    create_task, finish_task
from helpers.tg_helpers import request_money, send_user_call_report, make_transcript_link
from misc.files import delete_files
from integrations.gs_api.sheets import GSLoader
from modules.assembly import Assembly
from modules.exceptions import LemurParseError
from modules.report_generator import ReportGenerator
from telegram_bot.helpers import txt
from config import config as cfg


def on_assembly_exception(
        ex: Exception,
) -> bool:
    """
    Вызывается, если во время обработки задачи AssemblyAI произошла ошибка.

    Данная функция регулирует дальнейшие попытки обработать задачу:
    1. Возвращает False, если нужно повторить попытку.
    2. Возвращает True, если нужно прекратить дальнейшие попытки.
    3. Возбуждает исключение, если нужно прекратить дальнейшие попытки + передать исключение вовне.
    """
    if isinstance(ex, LemurParseError):
        logger.error(f'{ex.args[0]}: Lemur response: {ex.lemur_response}.')
        raise ex

    elif isinstance(ex, LemurError):
        if (
                re.findall(r'max_output_size of \d+ is too small to fulfill request', ex.args[0])
            or
                'the following transcripts have no text' in ex.args[0]
        ):
            logger.error(ex)
            raise ex

    return False


def get_assembly(
        audio: Audiofile,
        task: Task,
        message: Optional[Message] = None,
        prompt_extra: Optional[dict] = None,
) -> Assembly:
    """
    Транскрибация и анализ.
    Используется модель активного режима работы пользователя.

    Если такая модель не найдена в настройках, то:
    1) возникает исключение;
    2) отправляется сообщение в Telegram-бот (если передан аргумент `message`).
    """
    final_model = task.report.final_model
    if final_model not in cfg.TASK_MODELS_LIST:
        if message:
            message.reply(txt.error_unsupported_ai_model)
        raise Exception('Неизвестная модель для анализа.')

    context = task.report.context
    assembly = Assembly(context, final_model=final_model)

    # Вопросы, на которые должна ответить нейронная сеть.
    mode_questions = task.report.get_ai_columns()

    return retry_call(
        assembly.analyze_audio_with_task,
        fargs=[audio, task, mode_questions], fkwargs={'prompt_extra': prompt_extra},
        tries=4, delay=1, backoff=4, logger=logger,
        on_exception=on_assembly_exception,
    )


def build_telegram_error(ex: Exception) -> Optional[str]:
    # Отправка сообщения об ошибке в Telegram.
    if isinstance(ex, LemurError):
        if re.findall(r'max_output_size of \d+ is too small to fulfill request', ex.args[0]):
            error = ('Недостаточное количество выходных токенов (4000). '
                                     'Сократите количество выводов в отчете.')
            return error
        elif 'the following transcripts have no text' in ex.args[0]:
            error = 'Пустой аудиофайл.'
            return error

    return None


def process_telegram_audio(
        audio: Audiofile,
        cli: Client,
        message_with_audio: Message,
        db_user: User,
        info_message: Message,
        report: Report,
) -> None:
    """
    Обработчик аудиозаписи Telegram-интеграции.
    """

    # Когда не хватает баланса
    if not_enough_company_balance(db_user.company, audio.duration_in_sec):
        request_money(cli, db_user, audio.duration_in_sec)
        delete_files([audio.path])
        return

    # Списание баланса
    db_user.company.add_balance(-audio.duration_in_sec)

    task = create_task(audio.duration_in_sec,
                       audio.url,
                       report)
    logger.info(f"Создал новый TG Task {task.id}")

    try:
        # Прогнозируем время на анализ
        info_message.edit_text(txt.analyze_duration_min(audio.duration_in_sec))

        # Транскрибация и анализ
        assembly = get_assembly(audio, task, message=message_with_audio)

        # Обновление Task
        update_task_after_analysis(task, assembly, audio)

        # Ответы нейронной сети в порядке записи в Гугл Таблицу.
        sorted_analyze_data = task.get_sorted_analyze_data()
        answers_texts = [answer_text for _, answer_text in sorted_analyze_data]

        # Генерация отчета
        report_generator = ReportGenerator(transcript=assembly.transcript)
        txt_file_path: str = report_generator.generate_txt_report(sorted_analyze_data)

        # Подготовка данных для записи в таблицу.
        if cfg.SAVE_TRANSCRIPT_AS_TEXT:
            transcript_cell = report_generator.generate_transcript()
        else:
            transcript_cell = make_transcript_link(assembly.transcript.id)
        values_to_upload = GSLoader.get_call_default_upload_values(answers_texts, audio) + [transcript_cell]

        # Выгрузка в Гугл таблицу
        GSpreadTask.create(values_to_upload=json.dumps(values_to_upload), task=task)

        # Отправляем отчет пользователю
        info_message.delete()
        send_user_call_report(txt_file_path, message_with_audio, db_user, task.report,
                              caption='Анализ отобразится в таблице в течение 1 минуты.')

    except Exception as exc:
        db_user.company.add_balance(audio.duration_in_sec)
        delete_files([audio.path])
        update_task_with_error(task)
        logger.error(f"Ошибка при обработке аудио Task TG {task.id}: {exc}")
        telegram_error = build_telegram_error(exc)
        if telegram_error is not None:
            info_message.edit_text(telegram_error)
        else:
            raise

    else:
        # Завершение Task
        finish_task(task)
        # Удаление исходных файлов
        delete_files([audio.path, txt_file_path])


def get_task_extra_prompt(db_task: Task) -> dict:
    """
    Формирует дополнительные данные для вставки в промпт.
    """
    prompt_extra = {}

    task_settings = db_task.get_data().get('settings', {})

    # Если включена настройка «Добавить в промпт результаты анализа предыдущего звонка».
    if task_settings.get('consider_previous_call') and db_task.deal:

        # Все задачи отчета, связанные с данной сделкой.
        user_deal_tasks = Task.select().where(
            Task.report == db_task.report,
            Task.deal == db_task.deal,
            Task.status == Task.StatusChoices.DONE,
        )
        # Самая недавняя обработанная задача пользователя этой же сделки.
        prev_task = user_deal_tasks.where(Task.id != db_task.id).order_by(Task.id.desc()).first()

        if prev_task:
            mode_questions = db_task.report.get_ai_columns()
            mode_answers = (
                ModeAnswer
                .select()
                .where(
                    ModeAnswer.task == prev_task,
                    ModeAnswer.question.in_(mode_questions),
                )
            )
            values = {ma.question.id: ma.answer_text for ma in mode_answers}
            for mq in mode_questions:
                if mq.id not in values:
                    values[mq.id] = 'Колонка отсутствовала'
            try:
                prompt_extra['previous_call_analyze_data'] = json.dumps(values, ensure_ascii=False)
            except JSONDecodeError:
                logger.error(f'Не удалось извлечь результаты анализа предыдущего звонка. '
                             f'ID текущей задачи: {db_task.id=}. '
                             f'Проверьте структуру результата анализа для задачи {prev_task.id}.')

    return prompt_extra


def get_process_task_cost(audio: Audiofile, prompt_extra: dict) -> int:
    """
    Вычисляет стоимость анализа звонка с учетом дополнительных настроек анализа.
    """
    # Базовая стоимость анализа звонка.
    seconds_cost = audio.duration_in_sec

    # Если анализ с учетом предыдущего звонка.
    if 'previous_call_analyze_data' in prompt_extra:
        seconds_cost = max(seconds_cost, 120)

    return seconds_cost


def process_custom_webhook_audio(
        audio: Audiofile,
        db_task: Task,
        basic_data: list = None,
) -> None:
    """
    Обработчик аудиозаписи
    """
    company = db_task.report.integration.company

    db_task.duration_sec = audio.duration_in_sec
    db_task.file_url = audio.url
    db_task.save(only=['duration_sec', 'file_url'])

    task_data = db_task.get_data()

    # Проверка баланса.
    if not_enough_company_balance(company, audio.duration_in_sec):
        task_data.update(**{"status": "cancelled",
                            "message": "Недостаточно средств",
                            "status_message": "Недостаточно средств"})
        db_task.save_data(task_data)
        db_task.status = Task.StatusChoices.CANCELLED
        db_task.save()
        delete_files([audio.path])
        return

    prompt_extra = get_task_extra_prompt(db_task)
    seconds_cost = get_process_task_cost(audio, prompt_extra)

    # Списание баланса
    company.add_balance(-seconds_cost)
    error_message = None

    try:
        # Транскрибация и анализ
        try:
            assembly = get_assembly(audio, db_task, prompt_extra=prompt_extra)
        except:
            error_message = 'Не удалось транскрибировать или проанализировать звонок.'
            raise
        # Сохраняем результат анализа.
        db_task.analyze_data = json.dumps(assembly.analyze_dict)
        db_task.save(only=['analyze_data'])

        # Генерация json отчета и сохранение его в db_task.data
        report_generator = ReportGenerator(transcript=assembly.transcript)
        try:
            transcript_text = report_generator.generate_transcript()
        except:
            error_message = 'Не удалось сгенерировать отчет о звонке.'
            raise

        data_to_update = {
            "report_status": "done",
            "transcript": transcript_text,
            "result": {},
        }

        # Сохраняем детальный транскрипт (как нам приходит от Assembly).
        if task_data.get('settings', {}).get('advance_transcript'):
            data_to_update['result'] = task_data.get('result', {})
            transcript_response = assembly.transcript.json_response
            data_to_update['result']['advance_transcript_data'] = {
                'audio_duration': transcript_response['audio_duration'],
                'text': transcript_response['text'],
                'words': transcript_response['words'],
            }

        task_data.update(**data_to_update)
        db_task.save_data(task_data)

        # Подготовка данных для записи в таблицу.
        if cfg.SAVE_TRANSCRIPT_AS_TEXT:
            transcript_cell = transcript_text
        else:
            transcript_cell = make_transcript_link(assembly.transcript.id)

        # Ответы нейронной сети в порядке записи в Гугл Таблицу.
        sorted_analyze_data = db_task.get_sorted_analyze_data()
        answers_texts = [answer_text for _, answer_text in sorted_analyze_data]

        if basic_data is None:
            values_to_upload = GSLoader.get_call_default_upload_values(answers_texts, audio) + [transcript_cell]
        else:
            values_to_upload = [get_refresh_time(), assembly.transcript.audio_duration] + basic_data + answers_texts + [transcript_cell]

        # Выгрузка в Гугл таблицу
        GSpreadTask.create(values_to_upload=json.dumps(values_to_upload), task=db_task)

    except Exception as ex:

        # Возвращаем пользователю потраченные секунды баланса.
        company.add_balance(seconds_cost)

        # Сохраняем текст ошибки в базу данных и в лог.
        if error_message is None:
            error_message = 'Неизвестная ошибка при обработке аудио.'
        update_task_with_error(db_task, error=error_message, ex=ex)

        task_data.update(**{"report_status": "error", "status_message": error_message})
        db_task.save_data(task_data)
        db_task.save()
        raise

    else:
        # Обновление Таска в БД
        db_task.transcript_id = assembly.transcript.id
        db_task.analyze_id = assembly.lemur_response.request_id
        db_task.assembly_duration = assembly.transcript.audio_duration
        db_task.status = Task.StatusChoices.DONE
        db_task.save()

    finally:
        # Удаление исходных файлов
        delete_files([audio.path])


def populate_crm_columns(
        task: Task,
        crm_values_to_upload: List[dict],
):
    logger.info('Сохраняем CRM-значения, выгружаемые в Гугл Таблицу, в CRM-колонки.')
    answers_created = 0

    for item in crm_values_to_upload:

        # Сохраняем только значения, которые связаны с CRM-колонками.
        crm_id = item.get('crm_id')
        if crm_id is None:
            continue

        # Последний индекс колонки среди всех активных колонок отчета.
        last_column_index = (
            ModeQuestion
            .select(ModeQuestion.column_index)
            .where(ModeQuestion.report == task.report,
                   ModeQuestion.is_active == True)
            .order_by(ModeQuestion.column_index.desc())
            .limit(1)
        ).scalar() or 0
        # Индекс новой колонки.
        new_column_index = last_column_index + 1

        # Создаем или получаем колонку.
        question, created = ModeQuestion.get_or_create(
            report=task.report,
            calc_type=ModeQuestionCalcType.CRM,
            crm_entity_type=item.get('crm_entity_type'),
            crm_id=crm_id,
            defaults={
                'is_active': True,
                'short_name': f'CRM {crm_id}',
                'column_index': new_column_index,
                'question_text': '',
            }
        )
        if not created and not question.is_active:
            # Если колонка уже существовала и была отключена, то не сохраняем ответ.
            continue
        else:
            # Если колонка включена, то сохраняем ответ в базу данных.
            ModeAnswer.create(task=task, question=question, answer_text=item['value'])
            answers_created += 1

    logger.info(f'Сохранили значения из basic_data в CRM-колонки: {answers_created} шт. '
                f'Количество элементов в basic_data: {len(crm_values_to_upload)}.')



def process_crm_call(
        audio: Audiofile,
        company: Company,
        crm_values_to_upload: List[dict],
        task: Task,
) -> Optional[str]:
    """
    Обработчик аудиозаписи без уведомлений.
    Списываем секунды баланса на основе ответа от нейросетки.

    :crm_values_to_upload:  Содержит значения ячеек для выгрузки в Гугл Таблицу.
                            Если для элемента указан crm_id, то значение сохраняется в виде ModeAnswer на CRM-колонку.
                            Если crm_id не задан, то значение будет выгружено только в Гугл Таблицу без сохранения в БД.
    """
    prompt_extra = {}
    try:
        # Ищем ответственного по crm_id.
        for item in crm_values_to_upload:
            if item.get('crm_entity_type') is None and item.get('crm_id') == 'responsible_user_name':
                prompt_extra['Менеджер'] = item['value']
                break
    except IndexError:
        pass

    basic_data = [x['value'] for x in crm_values_to_upload]

    try:
        # Транскрибация и анализ
        assembly = get_assembly(audio, task, prompt_extra=prompt_extra)
        update_task_after_analysis(task, assembly, audio)

        # Ответы нейронной сети в порядке записи в Гугл Таблицу.
        sorted_analyze_data = task.get_sorted_analyze_data()
        answers_texts = [answer_text for _, answer_text in sorted_analyze_data]

        report_generator = ReportGenerator(transcript=assembly.transcript)

        # Подготовка данных для записи в таблицу.
        if cfg.SAVE_TRANSCRIPT_AS_TEXT:
            transcript_cell = report_generator.generate_transcript()
        else:
            transcript_cell = make_transcript_link(assembly.transcript.id)
        values_to_upload = basic_data + answers_texts + [transcript_cell]

        # Выгрузка в Гугл таблицу
        GSpreadTask.create(values_to_upload=json.dumps(values_to_upload), task=task)

        populate_crm_columns(task, crm_values_to_upload)

    except Exception as ex:
        update_task_with_error(task, error='Ошибка при обработке аудио Task', ex=ex)
        logger.error(f"Ошибка при обработке аудио Task {task.id}: {ex}")
        raise

    else:
        # Снимаем с баланса продолжительность, обработанную нейронной сетью.
        company.add_balance(-assembly.transcript.audio_duration)
        finish_task(task)
        string_report = report_generator.generate_string_report(sorted_analyze_data)

    finally:
        # Удаление исходных файлов
        delete_files([audio.path])

    return string_report
