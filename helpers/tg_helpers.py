from loguru import logger
from pyrogram import Client, types
from pyrogram.types import CallbackQuery, Message

from config import config as cfg
from data.models import User, Payment, Task, Mode
from integrations.robokassa.payment import create_robokassa_payment_link
from helpers.db_helpers import create_payment
from telegram_bot.helpers import txt, markup


def buy_minutes_handler(cli: Client, q: CallbackQuery, db_user: User):
    """
    Отправка сообщения со ссылкой на оплату через Robokassa
    """
    minutes_to_buy = int(q.data.split("_")[1])
    invoice_sum = minutes_to_buy * cfg.PRICE_PER_MINUTE_IN_RUB

    # Создание платежа в БД
    payment: Payment = create_payment(db_user, invoice_sum, minutes_to_buy)

    # Генерация ссылки на оплату
    payment_link = create_robokassa_payment_link(payment, minutes_to_buy)

    # Отправка сообщения пользователю со ссылкой на оплату
    cli.send_message(db_user.tg_id, txt.your_payment_link(minutes_to_buy),
                     reply_markup=markup.robokassa_pay_button(payment_link, invoice_sum))


def get_tg_file_id_from_message(message: Message):
    """
    Получение file_id аудиофайла
    """
    if message.audio:
        tg_file_id = message.audio.file_id
    elif message.video:
        tg_file_id = message.video.file_id
    elif message.document and ('audio' in message.document.mime_type or 'video' in message.document.mime_type):
        tg_file_id = message.document.file_id
    else:
        tg_file_id = False

    return tg_file_id


def get_tg_file_name(message: Message):
    """
    Получение названия аудиофайла
    """
    tg_file_name = None

    if message.audio:
        tg_file_name = message.audio.file_name
    elif message.document and ('audio' in message.document.mime_type or 'video' in message.document.mime_type):
        tg_file_name = message.document.file_name

    return tg_file_name


def request_money(cli: Client, db_user: User, audio_duration_in_sec: int):
    """
    Запрос оплаты
    """
    minutes_to_go = round(audio_duration_in_sec / 60, 2)
    current_balance = db_user.get_payer_balance()
    db_user_minutes_balance = round(current_balance / 60, 2)

    cli.send_message(db_user.tg_id, txt.request_payment_light(db_user_minutes_balance, minutes_to_go))


def send_user_call_report(txt_file_path, message_with_audio, db_user: User):
    """
    Отправляет пользователю текстовый отчет и кнопку перехода на таблицу
    """
    db_mode: Mode = db_user.get_active_mode()
    file_name = f"Текстовый отчет {len(db_user.tasks) + 1}.txt"

    message_with_audio.reply_document(txt_file_path,
                                      file_name=file_name,
                                      reply_markup=markup.google_sheets(db_mode.sheet_url),
                                      quote=True)


def send_admin_call_report(cli: Client, message: Message, file_path, db_task: Task, chat_id=cfg.ADMIN_CHAT_ID):
    """
    Отправляет звонок и транскрипт в админский чат
    """
    tg_user: types.User = cli.get_users(db_task.user.tg_id)
    tg_username = "@" + tg_user.username if tg_user.username else ""
    db_user: User = db_task.user
    db_mode: Mode = db_user.get_active_mode()

    massage_with_audio: Message = message.forward(chat_id)
    massage_with_audio.reply_document(file_path, caption=txt.admin_call_report(tg_username, db_user, db_task),
                                      reply_markup=markup.google_sheets(db_mode.sheet_url))


def get_user_info(cli, tg_ids):
    """
    Получение информации о пользователях: full_name, tg_id, username

    Пример ответа:
    {833830: {'full_name': 'Андрей Сергеевич',
              'tg_id': 833830,
              'username': 'gorbunov'},
    }
    """
    users_info = []
    for tg_id in tg_ids:
        try:
            user = cli.get_users(tg_id)
        except ValueError:
            logger.warning(f'Не удалось получить данные пользователя Telegram {tg_id=}.')
            full_name = ''
            username = ''
        else:
            full_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
            username = user.username

        users_info.append({'tg_id': tg_id, 'full_name': full_name, 'username': username})

    return {info['tg_id']: info for info in users_info}


def make_transcript_link(transcript_id):
    """
    Создание ссылки на транскрипт
    """
    return f"{cfg.BOT_LINK}/?start=get-transcript_{transcript_id}"

