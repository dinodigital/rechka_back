from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.const import CBData
import config.config as cfg
from data.models import User, Report, Integration, IntegrationServiceName, ActiveTelegramReport


def with_close_btn():
    """
    Кнопка удаления сообщения
    """
    return InlineKeyboardMarkup([[InlineKeyboardButton(text="» Скрыть «", callback_data="close")]])


def easy_inline_markup(buttons=None):
    """
    Упрощенная генерация inline клавиатуры.

    1 кнопка
    [[(text, callback)]]

    2 кнопки в сроке
    [[(text, callback), (text, callback)]]

    2 строки по 2 кнопки
    [
        [("Да", "callback_yes"), ("Нет", "callback_no")],
        [("1", "callback_1"), ("2", "callback_2")],
    ]

    Кнопка с url
    ("Название кнопки", "http://ссылка", "url")
    """

    # Кнопка закрыть
    if not buttons:
        return with_close_btn()

    bot_buttons = []
    for row in buttons:
        bot_row = []
        for button in row:
            if 'url' in button:
                bot_row.append(InlineKeyboardButton(text=button[0], url=button[1]))
            else:
                bot_row.append(InlineKeyboardButton(text=button[0], callback_data=button[1]))
        bot_buttons.append(bot_row)

    return InlineKeyboardMarkup(bot_buttons)


def minute_packs():
    """
    Кнопки покупки пакетов минут
    """
    pack_1 =    100
    pack_2 =    500
    pack_3 =  1_000
    pack_4 =  5_000
    pack_5 = 10_000

    def generate_button(pack):
        """
        Генератор inline кнопки оплаты
        """
        return [(f"{pack} минут - {pack * cfg.PRICE_PER_MINUTE_IN_RUB} ₽", f"{CBData.buy_minute_pack}_{pack}")]

    return easy_inline_markup([
        generate_button(pack_1),
        generate_button(pack_2),
        generate_button(pack_3),
        generate_button(pack_4),
        generate_button(pack_5)
    ])


def pay_test_button(minutes):
    return easy_inline_markup([[(f"{minutes} минут - {minutes * cfg.PRICE_PER_MINUTE_IN_RUB} ₽",
                                 f"{CBData.buy_minute_pack}_{minutes}")]])


def robokassa_pay_button(payment_link, invoice_sum):
    """
    Кнопка оплаты через сервис Robokassa
    """
    return easy_inline_markup([[(f"Оплатить {invoice_sum} ₽", f"{payment_link}", "url")]])


def reports_markup(db_user: User):
    """
    Кнопки отчетов
    """
    # Telegram-интеграции компании.
    integrations = Integration.select().where(Integration.company == db_user.company,
                                              Integration.service_name == IntegrationServiceName.TELEGRAM)
    # Активные отчеты Telegram-интеграций компании.
    reports = Report.select().where(Report.integration.in_(integrations),
                                    Report.active == True)
    # Активный Telegram-отчет пользователя.
    active_tg_report = ActiveTelegramReport.get_or_none(user=db_user)

    buttons = []
    for report in reports:
        if active_tg_report and active_tg_report.report == report:
            btn_name = f"🟢 {report.name}"
            cb_data = "none"
        else:
            btn_name = report.name
            cb_data = f"{CBData.change_report}_{report.id}"
        buttons.append([(btn_name, cb_data)])

    return easy_inline_markup(buttons)


def google_sheets(url):
    """
    Ссылка на Гугл таблицу для сообщения с готовым анализом
    """
    return easy_inline_markup([[("📊 Смотреть в таблице", url, "url")]])
