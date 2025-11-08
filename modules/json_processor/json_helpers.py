import json

from gspread import Spreadsheet
from gspread.urls import SPREADSHEET_DRIVE_URL
from pyrogram.types import Message

from data.models import Integration, User, UserMode, Report, Mode
from helpers.db_helpers import create_mode_from_json
from integrations.gs_api.sheets import clone_template, generate_first_row, update_first_row
from modules.json_processor.struct_checkers import is_create_mode_json, is_create_report_json, is_update_report_json
from telegram_bot.helpers import txt


def create_report_with_json(message: Message, full_json: dict):
    """
    Создание отчета
    """
    report_id = full_json.get("report_id")
    if report_id is not None:
        if not is_update_report_json(full_json):
            return message.reply("Некорректный json файл")

        report: Report = Report.get_or_none(Report.id == report_id)
        if not report:
            return message.reply(f"Report с id {report_id} не найден")

        mode_id = full_json.get("mode", "")
        mode: Mode = Mode.get_or_none(Mode.id == mode_id)

        if not mode:
            return message.reply(f"Mode с id {mode_id} не найден")

        name = full_json.get("name", "")
        priority = full_json.get("priority", "")
        settings = full_json.get("settings", "")
        filters = full_json.get("filters", "")
        crm_data = full_json.get("crm_data", "")
        active = full_json.get("active")
        if active is not None:
            report.active = active

        report.name = name
        report.priority = priority
        report.mode = mode
        report.settings = json.dumps(settings)
        report.filters = json.dumps(filters)
        report.crm_data = json.dumps(crm_data)
        report.save()
        log_txt = f"Обновил отчет {report_id}."
        return message.reply(log_txt)

    if not is_create_report_json(full_json):
        return message.reply("Некорректный json файл")

    telegram_id = full_json.get("telegram_id", "")
    user = User.get_or_none(User.tg_id == telegram_id)

    if user:
        integration = Integration.get_or_none(Integration.user == user)
        if not integration:
            return message.reply("Интеграция не найдена")
    else:
        return message.reply(f"Пользователь с telegram_id {telegram_id} не найден")

    mode_id = full_json.get("mode", "")
    mode: Mode = Mode.get_or_none(Mode.id == mode_id)

    if not mode:
        return message.reply(f"Mode с id {mode_id} не найден")

    name = full_json.get("name", "")
    priority = full_json.get("priority", "")
    settings = full_json.get("settings", "")
    filters = full_json.get("filters", "")
    crm_data = full_json.get("crm_data", "")

    report: Report = Report.create(
        name=name,
        priority=priority,
        integration=integration,
        mode=mode,
        settings=json.dumps(settings),
        filters=json.dumps(filters),
        crm_data=json.dumps(crm_data)
    )
    log_txt = f"Создал отчет с Bitrix24. tg_id: {telegram_id}, integration_id: {integration.id}, report: {report.id}"
    return message.reply(log_txt)


def create_mode_with_json(message: Message, full_json: dict):
    """
    Создание режима работы бота с помощью JSON файла
    """

    # Проверяем json файл на соответствие нашей форме
    if not is_create_mode_json(full_json):
        return message.reply("Некорректный json файл")

    if full_json["sheet_id"] is None:
        # Клонирование гугл таблицы
        message.reply("Создаю гугл таблицу")
        sheet: Spreadsheet = clone_template()

        # Обновление первой строки
        first_row = generate_first_row(full_json)
        update_first_row(sheet, first_row)
        message.reply(
            f"✅ Google отчет создан:\n{sheet.url}\n\n<i><u>Настройте ширину колонок</u> в таблице, чтобы отчет для клиента выглядел красиво</i>",
            disable_web_page_preview=True)
        sheet_id = sheet.id
    else:
        sheet_id = full_json["sheet_id"]
        sheet_url = SPREADSHEET_DRIVE_URL % sheet_id
        message.reply(
            f"✅ Google отчет создан:\n{sheet_url}\n\n<i><u>Настройте ширину колонок</u> в таблице, чтобы отчет для клиента выглядел красиво</i>",
            disable_web_page_preview=True)

    # Создание нового Mode в БД
    db_mode = create_mode_from_json(full_json, sheet_id)

    # Создание нового UserMode
    UserMode.create(mode=db_mode)

    # Ссылка админу для передачи клиенту
    message.reply(txt.mode_created(db_mode), disable_web_page_preview=True)
