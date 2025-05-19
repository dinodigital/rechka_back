import pyrogram
from bitrix24 import BitrixError
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from integrations.bitrix.bitrix_api import Bitrix24
from modules.audio_processor import process_audio
from modules.audiofile import Audiofile
from data.models import User, Integration, Task
from modules.json_processor.json_processor import process_json
from telegram_bot.helpers import txt
from telegram_bot.helpers.crm import create_bitrix_contact_and_deal
from telegram_bot.helpers.filters import audio_video_filter, admin_filter, json_filter
import config.config as cfg
import traceback


# Состояния диалогов с пользователями. Ключи – tg_id.
# https://stackoverflow.com/a/70154780
user_context = {}

class AppStates:
    REQUEST_PHONE = 1
    RECEIVE_PHONE = 2


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

    # Нужно ли запросить номер телефона пользователя перед анализом аудио.
    request_phone = False

    user_tasks = Task.select().where(Task.user == db_user)
    if user_tasks.count() == 0:
        integration = Integration.get_or_none(Integration.id == cfg.BITRIX24_RECHKA_INTEGRATION_ID)
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)
        try:
            contacts = bx24.get_contact_list(cfg.BITRIX24_CONTACT_TG_ID_FIELD_NAME, db_user.tg_id)
        except BitrixError:
            # Не запрашиваем номер телефона, позволяем проанализировать звонок.
            pass
        else:
            if len(contacts) == 0:
                request_phone = True

    if request_phone:
        logger.info('Запрашиваем номер телефона пользователя Telegram перед анализом аудио.')
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton('Отправить номер телефона', request_contact=True)]],
            resize_keyboard=True
        )
        message.reply('Для выполнения анализа, пожалуйста, отправьте свой номер телефона.', reply_markup=keyboard)
        user_context[db_user.tg_id] = AppStates.REQUEST_PHONE
    else:
        try:
            info_message: Message = message_with_audio.reply("💾 Скачиваю аудиофайл")
            audio = Audiofile().load_from_tg_message_with_audio(cli, message_with_audio)
            # Для точности списания баланса.
            db_user: User = User.get_or_none(tg_id=tg_id)
            process_audio(audio, cli, message_with_audio, db_user, info_message)

        except Exception as e:
            logger.error(f"Ошибка обработки звонка: {e}")
            cli.send_message(tg_id, txt.error_try_again)
            cli.send_message(cfg.ERROR_CHAT_ID, f"⚠️ Ошибка обработки аудиозаписи:\n{traceback.format_exc()}")
            raise

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.contact)
def contact_handler(cli: Client, message: Message):
    tg_id = message.from_user.id

    if user_context[tg_id] == AppStates.REQUEST_PHONE:
        user_context[tg_id] = AppStates.RECEIVE_PHONE

        db_user = User.get(tg_id=tg_id)

        # Получаем номер телефона из сообщения
        phone_number = message.contact.phone_number
        username = message.from_user.username

        logger.info(f'Создаем Контакт и Сделку в Битрикс для пользователя Telegram tg_id={db_user.tg_id=}.')
        try:
            contact_id, deal_id = create_bitrix_contact_and_deal(db_user,
                                                                 phone_number,
                                                                 username=username,
                                                                 raise_on_exists=True)
        except Exception as ex:
            logger.error(f'Не удалось создать сделку или контакт в Битрикс24 для '
                         f'пользователя Telegram tg_id={db_user.tg_id=}. Ошибка: {ex}')
        else:
            logger.info(f'Созданы карточки Контакта (ID {contact_id}) и Сделки (ID {deal_id}) для '
                        f'пользователя Telegram tg_id={db_user.tg_id}.')
            cli.send_message(db_user.tg_id,
                             'Регистрация успешно завершена. Теперь вы можете анализировать звонки. '
                             'Пожалуйста, отправьте аудиофайл повторно.',
                             reply_markup=ReplyKeyboardRemove())

    else:
        logger.info('Получили номер телефона в боте в неизвестном состоянии.')


@Client.on_message(~filters.bot & admin_filter & json_filter, group=30)
def admin_json_handler(cli: Client, message: Message):
    """
    Обработчик присланного json файла нового клиента. Только для АДМИНОВ.
    """
    process_json(message)

    raise pyrogram.StopPropagation
