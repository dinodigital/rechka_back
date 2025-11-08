import traceback

import pyrogram
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message

import config.config as cfg
from data.models import User, ActiveTelegramReport
from modules.audio_processor import process_telegram_audio
from modules.audiofile import Audiofile
from modules.json_processor.json_processor import process_json
from telegram_bot.helpers import txt
from telegram_bot.helpers.filters import audio_video_filter, admin_filter, json_filter


@Client.on_message(~filters.bot & audio_video_filter, group=20)
def audio_handler(cli: Client, message: Message):
    """
    Обработчик присланного аудиофайла
    """
    tg_id = message.from_user.id
    db_user: User = User.get_or_none(tg_id=tg_id)
    message_with_audio = message

    if not db_user:
        cli.send_message(tg_id, txt.error_no_db_user)
        return

    # Если у пользователя не указан активный отчет, сообщаем ему об этом.
    active_tg_report = ActiveTelegramReport.get_or_none(user=db_user)
    if not active_tg_report or not active_tg_report.report.active:
        logger.warning(f'Telegram: Не удалось найти активный отчет для пользователя ID={db_user.id}.')
        cli.send_message(tg_id, txt.error_no_active_report)
        return

    report = active_tg_report.report

    info_message: Message = message_with_audio.reply("💾 Скачиваю аудиофайл")
    try:
        audio = Audiofile().load_from_tg_message_with_audio(cli, message_with_audio)
        # Для точности списания баланса.
        db_user: User = User.get_or_none(tg_id=tg_id)
        process_telegram_audio(audio, cli, message_with_audio, db_user, info_message, report)

    except Exception as e:
        logger.error(f"Ошибка обработки звонка: {e}")
        cli.send_message(tg_id, txt.error_try_again)
        cli.send_message(cfg.ERROR_CHAT_ID, f"⚠️ Ошибка обработки аудиозаписи:\n{traceback.format_exc()}")
        raise

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & admin_filter & json_filter, group=30)
def admin_json_handler(cli: Client, message: Message):
    """
    Обработчик присланного json файла нового клиента. Только для АДМИНОВ.
    """
    process_json(message)

    raise pyrogram.StopPropagation
