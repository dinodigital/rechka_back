import pyrogram
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message


@pyrogram.Client.on_callback_query(group=1)
def callback_logger(cli: Client, q: CallbackQuery):
    logger.info(f"tg_id: '{q.from_user.id}'  callback: '{q.data}'")


@Client.on_message(~filters.bot & ~filters.channel & ~filters.group, group=1)
def message_logger(cli: Client, message: Message):
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")



