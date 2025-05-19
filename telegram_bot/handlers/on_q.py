from pyrogram import Client
from pyrogram.types import CallbackQuery

from config.const import CBData
from data.models import User
from telegram_bot.helpers import markup, txt
from helpers.tg_helpers import buy_minutes_handler


def change_mode_handler(cli: Client, q: CallbackQuery, db_user: User):
    """
    Смена режима бота
    """
    mode_id = q.data.split("_")[1]
    db_user.mode_id = mode_id
    db_user.save()
    q.edit_message_text(txt.cabinet(db_user), reply_markup=markup.modes_markup(db_user), disable_web_page_preview=True)


@Client.on_callback_query()
def pyrogram_callback_handler(cli: Client, q: CallbackQuery):
    tg_id = q.from_user.id
    db_user: User = User.get_or_none(tg_id=tg_id)

    if q.data == "close":
        q.message.delete()

    # Генерация сообщения о покупке минус со ссылкой Robokassa
    elif CBData.buy_minute_pack in q.data:
        buy_minutes_handler(cli, q, db_user)

    # Смена режима бота
    elif CBData.change_mode in q.data:
        change_mode_handler(cli, q, db_user)
