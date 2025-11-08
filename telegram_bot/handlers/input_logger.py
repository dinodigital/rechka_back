from typing import List

import pyrogram
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message


@pyrogram.Client.on_callback_query(group=1)
def callback_logger(cli: Client, q: CallbackQuery):
    logger.info(f"tg_id: '{q.from_user.id}'  callback: '{q.data}'")


def get_message_attachment_types(message: Message) -> List[str]:
    result = []

    if message.voice:
        result.append('Voice message')
    if message.photo:
        result.append(f'Photo ({len(message.photo)})' if isinstance(message.photo, list) else 'Photo')
    if message.video:
        result.append('Video')
    if message.document:
        result.append(f'Document ({len(message.document)})' if isinstance(message.document, list) else 'Document')
    if message.audio:
        result.append('Audio')
    if message.sticker:
        result.append('Sticker')
    if message.location:
        result.append('Location')
    if message.contact:
        result.append('Contact')
    if message.venue:
        result.append('Venue')
    if message.poll:
        result.append('Poll')
    if message.game:
        result.append('Game')
    if message.animation:
        result.append('Animation')
    if message.video_note:
        result.append('Video note')

    # Если вложений нет.
    if not result:
        if message.empty:
            result.append('Empty message')
        elif message.service:
            result.append('Service message')
        else:
            result.append('No attachment')

    return result


@Client.on_message(~filters.bot & ~filters.channel & ~filters.group, group=1)
def message_logger(cli: Client, message: Message):
    attachment_types = get_message_attachment_types(message)
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'  attachments: {', '.join(attachment_types)}")
