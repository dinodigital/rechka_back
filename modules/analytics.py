from gspread.utils import ValueInputOption
from loguru import logger

from config.config import ANALYTICS_SHEET_ID
from data.models import Task, User
from integrations.gs_api.sheets import SheetsApi
from misc.time import get_refresh_time


def upload_tasks_to_sheet(gs_api: SheetsApi):
    logger.info("Выгружаю Task-и из базы данных в Гугл таблицу")
    sheet = gs_api.file.get_worksheet_by_id(1676939082)

    # Загрузка задач из базы данных
    tasks_query = Task.select(
        Task.id, Task.created, Task.user_id, Task.duration_sec, Task.assembly_duration,
        Task.analyze_input_tokens, Task.analyze_output_tokens).where(
        (Task.status == Task.StatusChoices.DONE) | (Task.status.is_null())).order_by(Task.id.asc())

    # Форматируем данные для выгрузки
    data_to_upload = [["ID", "Created", "User ID", "Duration Sec", "Единичка", "Assembly Duration", "Input Tokens", "Output Tokens"]]
    for task in tasks_query:
        data_to_upload.append([task.id, task.created.strftime("%Y-%m-%d"), task.user_id, task.duration_sec, 1, task.assembly_duration, task.analyze_input_tokens, task.analyze_output_tokens])

    # Запись данных в лист, начиная с первой строки и первого столбца
    sheet.update(range_name='A1', values=data_to_upload, value_input_option=ValueInputOption.user_entered)
    logger.info("Выгрузка успешно завершена")


def upload_users_to_sheet(gs_api: SheetsApi):
    logger.info("Выгружаю User-ов из базы данных в Гугл таблицу")
    sheet = gs_api.file.get_worksheet_by_id(2106351851)

    # Загрузка задач из базы данных
    users_query = User.select(User.id, User.created, User.tg_id, User.seconds_balance, User.invited_by).order_by(User.id.asc())

    # Форматируем данные для выгрузки
    data_to_upload = [["Created", "ID", "User tg_id", "Seconds Balance", "Invited By", "Единичка"]]
    for user in users_query:
        data_to_upload.append(
            [user.created.strftime("%Y-%m-%d"), user.id, user.tg_id, user.seconds_balance, user.invited_by, 1]
        )

    # Запись данных в лист, начиная с первой строки и первого столбца
    sheet.update(range_name='A1', values=data_to_upload, value_input_option=ValueInputOption.user_entered)
    logger.info("Выгрузка успешно завершена")


def update_refresh_time(gs_api: SheetsApi):
    logger.info("Обновляю время обновления отчета")
    sheet = gs_api.file.get_worksheet_by_id(826792987)
    sheet.update(range_name='N2', values=[[get_refresh_time()]], value_input_option=ValueInputOption.user_entered)
    logger.info("Отчет успешно обновлен")


def refresh_analytics_sheet():
    gs_api = SheetsApi(ANALYTICS_SHEET_ID)
    upload_tasks_to_sheet(gs_api)
    upload_users_to_sheet(gs_api)
    update_refresh_time(gs_api)
