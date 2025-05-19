import json
from typing import Optional

from gspread.exceptions import GSpreadException
from pyrogram import Client
from pyrogram.types import Message
from retry import retry_call
from loguru import logger

from data.models import User, Task, Mode
from misc.time import get_refresh_time
from modules.audiofile import Audiofile
from helpers.db_helpers import not_enough_balance, create_db_task, update_task_after_analysis, update_task_with_error, \
    create_task, finish_task, update_task_with_google_error
from helpers.tg_helpers import request_money, send_admin_call_report, send_user_call_report, make_transcript_link
from misc.files import delete_files
from integrations.gs_api.sheets import GSLoader
from modules.assembly import Assembly
from modules.report_generator import ReportGenerator
from telegram_bot.helpers import txt
from config import config as cfg


def get_assembly(
        audio: Audiofile,
        db_user: User,
        task: Task,
        message: Optional[Message] = None,
        mode: Mode = None,
        prompt_extra: Optional[dict] = None,
) -> Assembly:
    """
    Транскрибация и анализ.
    Используется модель активного режима работы пользователя.

    Если такая модель не найдена в настройках, то:
    1) возникает исключение;
    2) отправляется сообщение в Telegram-бот (если передан аргумент `message`).
    """
    if mode is not None:
        lemur_params = mode.get_params()
    else:
        lemur_params = db_user.get_params()
    final_model = lemur_params.get('final_model')

    if final_model:
        if final_model in cfg.QUESTION_MODELS_LIST:
            return retry_call(
                Assembly(lemur_params).analyze_audio,
                fargs=[audio, task],
                tries=4, delay=1, backoff=4, logger=logger,
            )

        elif final_model in cfg.TASK_MODELS_LIST:
            return retry_call(
                Assembly(lemur_params).analyze_audio_with_task,
                fargs=[audio, task], fkwargs={'prompt_extra': prompt_extra},
                tries=4, delay=1, backoff=4, logger=logger,
            )

    if message:
        message.reply(txt.error_unsupported_ai_model)

    raise Exception


def process_audio(audio: Audiofile, cli: Client, message_with_audio: Message, db_user: User,
                  info_message: Message) -> None:
    """
    Обработчик аудиозаписи
    """

    # Когда не хватает баланса
    if not_enough_balance(db_user, audio.duration_in_sec):
        request_money(cli, db_user, audio.duration_in_sec)
        delete_files([audio.path])
        return

    # Списание баланса
    db_user.minus_seconds_balance(audio.duration_in_sec)

    task = create_task(user=db_user,
                       duration_sec=audio.duration_in_sec,
                       file_url=audio.url)
    logger.info(f"Создал новый TG Task {task.id}")

    try:
        # Прогнозируем время на анализ
        info_message.edit_text(txt.analyze_duration_min(audio.duration_in_sec))

        # Транскрибация и анализ
        assembly = get_assembly(audio, db_user, task, message=message_with_audio)

        # Обновление Task
        update_task_after_analysis(task, assembly, audio)

        # Генерация отчета
        report_generator = ReportGenerator(db_user, assembly.transcript, analyze_list=assembly.analyze_list)
        txt_file_path: str = report_generator.generate_txt_report()

        # Подготовка данных для записи в таблицу.
        if cfg.SAVE_TRANSCRIPT_AS_TEXT:
            transcript_cell = report_generator.generate_transcript()
        else:
            transcript_cell = make_transcript_link(assembly.transcript.id)
        values_to_upload = GSLoader.get_call_default_upload_values(assembly.analyze_list, audio) + [transcript_cell]
        # Выгрузка в Гугл таблицу
        GSLoader(db_user).upload_values_as_row(values_to_upload)

        # Отправляем отчет пользователю
        info_message.delete()
        send_user_call_report(txt_file_path, message_with_audio, db_user)

    except Exception as exc:
        db_user.add_seconds_balance(audio.duration_in_sec)
        delete_files([audio.path])
        update_task_with_error(task)
        logger.error(f"Ошибка при обработке аудио Task TG {task.id}: {exc}")
        raise

    else:
        # Завершение Task
        finish_task(task)
        # ADMIN: Отправка отчета админам
        send_admin_call_report(cli, message_with_audio, txt_file_path, task)
        # Удаление исходных файлов
        delete_files([audio.path, txt_file_path])


def process_custom_webhook_audio(audio: Audiofile, db_task: Task, basic_data: list = None) -> None:
    """
    Обработчик аудиозаписи
    """
    task_data = db_task.get_data()
    db_user = db_task.user

    # Когда не хватает баланса
    if not_enough_balance(db_user, audio.duration_in_sec):
        task_data.update(**{"status": "cancelled",
                            "message": "Недостаточно средств",
                            "status_message": "Недостаточно средств"})
        db_task.save_data(task_data)
        db_task.status = Task.StatusChoices.CANCELLED
        db_task.save()
        delete_files([audio.path])
        return

    # Списание баланса
    db_user.minus_seconds_balance(audio.duration_in_sec)
    error_message = None

    try:
        # Транскрибация и анализ
        try:
            assembly = get_assembly(audio, db_user, db_task)
        except:
            error_message = 'Не удалось транскрибировать или проанализировать звонок.'
            raise

        # Генерация json отчета и сохранение его в db_task.data
        report_generator = ReportGenerator(db_user, assembly.transcript, analyze_list=assembly.analyze_list)
        try:
            json_report: dict = report_generator.generate_json_report()
            transcript_text = report_generator.generate_transcript()
        except:
            error_message = 'Не удалось сгенерировать отчет о звонке.'
            raise

        data_to_update = {"call_report": json_report, "report_status": "done", "transcript": transcript_text}

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
        if basic_data is None:
            values_to_upload = GSLoader.get_call_default_upload_values(assembly.analyze_list, audio) + [transcript_cell]
        else:
            values_to_upload = [get_refresh_time(), assembly.transcript.audio_duration] + basic_data + assembly.analyze_list + [transcript_cell]

        # Выгрузка в Гугл таблицу
        GSLoader(db_user).upload_values_as_row(values_to_upload)

    except GSpreadException as ex:
        update_task_with_google_error(task=db_task, uploaded_data=values_to_upload, error=ex)
        logger.error(f"Ошибка при выгрузке в гугл таблицу Task {db_task.id}: {ex}")
        raise

    except Exception as ex:

        # Возвращаем пользователю потраченные секунды баланса.
        db_user.add_seconds_balance(audio.duration_in_sec)

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
        db_task.duration_sec = audio.duration_in_sec
        db_task.analyze_id = assembly.lemur_response.request_id
        db_task.analyze_data = json.dumps(assembly.analyze_list)
        db_task.file_url = audio.url
        db_task.assembly_duration = assembly.transcript.audio_duration
        db_task.status = Task.StatusChoices.DONE
        db_task.save()

    finally:
        # Удаление исходных файлов
        delete_files([audio.path])


def process_crm_call(audio: Audiofile, user: User, basic_data: list, task: Task = None, mode: Mode = None) -> Optional[str]:
    """
    Обработчик аудиозаписи без уведомлений.
    Списываем секунды баланса на основе ответа от нейросетки.
    """
    prompt_extra = {}
    try:
        prompt_extra['Ответственный менеджер (ФИО)'] = basic_data[3]
    except IndexError:
        pass

    values_to_upload = None
    try:
        # Транскрибация и анализ
        assembly = get_assembly(audio, user, task=task, mode=mode, prompt_extra=prompt_extra)
        if task is not None:
            update_task_after_analysis(task, assembly, audio)
        report_generator = ReportGenerator(user, assembly.transcript, analyze_list=assembly.analyze_list)

        # Подготовка данных для записи в таблицу.
        if cfg.SAVE_TRANSCRIPT_AS_TEXT:
            transcript_cell = report_generator.generate_transcript()
        else:
            transcript_cell = make_transcript_link(assembly.transcript.id)
        values_to_upload = basic_data + assembly.analyze_list + [transcript_cell]

        # Выгрузка в Гугл таблицу
        GSLoader(user, mode).upload_values_as_row(values_to_upload)

    except GSpreadException as ex:
        if task is not None:
            update_task_with_google_error(task=task, uploaded_data=values_to_upload, error=ex, mode=mode)
        logger.error(f"Ошибка при выгрузке в гугл таблицу Task {task.id}: {ex}")
        raise

    except Exception as ex:
        if task is not None:
            update_task_with_error(task, error='Ошибка при обработке аудио Task', ex=ex)
        logger.error(f"Ошибка при обработке аудио Task {task.id}: {ex}")
        raise

    else:
        # Снимаем с баланса продолжительность, обработанную нейронной сетью.
        user.minus_seconds_balance(assembly.transcript.audio_duration)
        if task is None:
            # Запись Таска в БД
            create_db_task(user, assembly, audio)
        else:
            finish_task(task)
        report = report_generator.generate_string_report(mode=mode)

    finally:
        # Удаление исходных файлов
        delete_files([audio.path])

    return report
