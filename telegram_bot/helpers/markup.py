from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.const import CBData
import config.config as cfg
from data.models import User, Mode


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


def modes_markup(db_user: User):
    """
    Кнопки режимов
    """
    def generate_button(db_mode: Mode):
        if db_user.mode_id == db_mode.mode_id:
            btn_name = f"🟢 {db_mode.name}"
            cb_data = "none"
        else:
            btn_name = db_mode.name
            cb_data = f"{CBData.change_mode}_{db_mode.mode_id}"
        return [(btn_name, cb_data)]

    modes = db_user.get_all_modes()
    buttons = []
    for mode in modes:
        buttons.append(generate_button(mode))

    return easy_inline_markup(buttons)


def google_sheets(url):
    """
    Ссылка на Гугл таблицу для сообщения с готовым анализом
    """
    return easy_inline_markup([[("📊 Смотреть в таблице", url, "url")]])
