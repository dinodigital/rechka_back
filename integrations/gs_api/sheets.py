from typing import List

import gspread
from gspread import Spreadsheet
from gspread.utils import ValueInputOption
from loguru import logger
from retry import retry

from config import config
from config.config import GOOGLE_PATH
from data.models import User, Mode
from integrations.gs_api.sheets_helpers import get_short_name_list
from misc.time import get_refresh_time


class SheetsApi:

    @retry(tries=4, delay=1, backoff=4)
    def __init__(self, sheet_id):
        self.gc = gspread.service_account(filename=GOOGLE_PATH)
        self.file = self.gc.open_by_key(sheet_id)
        self.analytics_sheet = self.file.sheet1
        self.row_number = 3

    @retry(tries=4, delay=1, backoff=4)
    def _insert_row(self, worksheet, row_number, values):
        """
        Вставить строку
        """
        # self.gc.login()
        return worksheet.insert_row(values, index=row_number, value_input_option=ValueInputOption.user_entered)

    @retry(tries=3, delay=1)
    def _insert_rows(self, worksheet, row_number, values):
        """
        Вставить несколько строк
        """
        # self.gc.login()
        return worksheet.insert_rows(values, row=row_number, value_input_option=ValueInputOption.user_entered)

    @retry(tries=3, delay=1)
    def _update_row(self, worksheet, row_number, values, to_letter, from_letter="A"):
        """
        Обновить строку
        """
        # self.gc.login()
        return worksheet.update(f"{from_letter}{row_number}:{to_letter}{row_number}",
                                [values],
                                value_input_option=ValueInputOption.user_entered)

    @retry(tries=3, delay=1)
    def _update(self, worksheet, row_number1, row_number2, values, to_letter, from_letter="A"):
        """
        Обновить строку
        """
        # self.gc.login()
        return worksheet.update(f"{from_letter}{row_number1}:{to_letter}{row_number2}",
                                values,
                                value_input_option=ValueInputOption.user_entered)

    def insert_row(self, values: list, row_number: int = None):
        """
        Вставить строку с продуктом
        """
        if not row_number:
            row_number = self.row_number

        logger.info(f"Вставляю строку #{row_number} в Гугл таблицу {self.file.id}. "
                    f"Загружаю {len(values)} значений (столбцов).")
        return self._insert_row(worksheet=self.analytics_sheet,
                                row_number=row_number,
                                values=values)

    def insert_rows(self, values: list, row_number: int):
        logger.info(f"Вставляю {len(values)} строк в Гугл таблицу {self.file.id}, начиная со строки #{row_number}.")
        return self._insert_rows(worksheet=self.analytics_sheet,
                                 row_number=row_number,
                                 values=values)


def generate_first_row(full_json):
    """
    Генерация первой строки
    """
    params_with_short_names = full_json['params']
    short_names = get_short_name_list(params_with_short_names)
    out_list = ["Дата добавления звонка", "Информация о звонке"]

    # Разбиваем столбцы по символам ";;", если они есть
    for item in short_names:
        if ";;" in item:
            out_list += item.split(";;")
        else:
            out_list.append(item)

    return out_list


@retry(tries=3, delay=1)
def clone_template(template_id=config.CLIENT_TEMPLATE_ID) -> Spreadsheet:
    """
    Функция клонирования Гугл отчета
    """
    logger.info("Подключаюсь к Google аккаунту")
    gc = gspread.service_account(filename=GOOGLE_PATH)
    # gc.login()

    logger.info("Клонирую шаблон клиентского отчета")
    sheet: Spreadsheet = gc.copy(template_id)

    logger.info("Создаю публичную ссылку")
    sheet.share(None, "anyone", "writer")

    return sheet


@retry(tries=3, delay=1)
def update_first_row(sheet, first_row):
    """
    Обновляет первую строку значениями списка first_row
    """
    cell_list = sheet.sheet1.range(2, 1, 2, len(first_row))
    for i, cell in enumerate(cell_list):
        cell.value = first_row[i]
    sheet.sheet1.update_cells(cell_list)


@retry(tries=3, delay=1)
def silent_create_default_spreadsheet(db_user: User) -> Spreadsheet:
    logger.info(f"Создаю Google таблицу для пользователя tg_id: {db_user.tg_id}")
    logger.info("Подключаюсь к Google аккаунту")
    gc = gspread.service_account(filename=GOOGLE_PATH)
    # gc.login()

    logger.info("Клонирую шаблон отчета")
    sheet: Spreadsheet = gc.copy(config.SHEETS_TEMPLATE_FILE_ID)

    logger.info("Настраиваю права доступа")
    sheet.share(None, "anyone", "writer")

    logger.info("Гугл отчет успешно настроен")

    return sheet


class GSLoader:

    def __init__(self, db_user: User, mode: Mode = None):
        if mode is None:
            mode = db_user.get_active_mode()
        self.db_mode = mode
        self.sh_api = SheetsApi(self.db_mode.sheet_id)

    @staticmethod
    def get_call_default_upload_values(answers_texts: List[str], audio) -> list:
        logger.info("Генерирую строку для выгрузки в гугл таблицу")
        call_info = f"Длительность: {audio.duration_min_sec}\nИмя файла: {audio.name}"
        values = [get_refresh_time(), call_info] + answers_texts
        return values

    def upload_values_as_row(self, values: list):
        """
        Добавляет строку в Гугл Таблицу с данными об обработанном звонке.
        """
        return self.sh_api.insert_row(values, self.db_mode.insert_row)
