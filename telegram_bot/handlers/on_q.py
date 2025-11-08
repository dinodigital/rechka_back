from pyrogram import Client
from pyrogram.types import CallbackQuery

from config.const import CBData
from data.models import User, Report, ActiveTelegramReport
from helpers.tg_helpers import buy_minutes_handler
from telegram_bot.helpers import markup, txt


def change_report_handler(cli: Client, q: CallbackQuery, db_user: User):
    """
    Активация отчета пользователя.
    """
    
    report_id = q.data.split('_')[-1]
    report = Report.get_or_none(id=report_id)
    if report is None or report.integration.company != db_user.company:
        cli.send_message(db_user.tg_id, 'Отчет не найден.')
        return 

    active_tg_report, created = ActiveTelegramReport.get_or_create(user=db_user, defaults={'report': report})
    if not created:
        active_tg_report.report = report
        active_tg_report.save(only=['report'])

    q.edit_message_text(txt.cabinet(db_user), reply_markup=markup.reports_markup(db_user), disable_web_page_preview=True)


@Client.on_callback_query()
def pyrogram_callback_handler(cli: Client, q: CallbackQuery):
    tg_id = q.from_user.id
    db_user: User = User.get_or_none(tg_id=tg_id)

    if q.data == "close":
        q.message.delete()

    # Генерация сообщения о покупке минус со ссылкой Robokassa
    elif CBData.buy_minute_pack in q.data:
        buy_minutes_handler(cli, q, db_user)

    # Активация отчета
    elif q.data.startswith(f'{CBData.change_report}_'):
        change_report_handler(cli, q, db_user)