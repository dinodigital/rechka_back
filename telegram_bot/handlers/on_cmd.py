import datetime
import time
from io import BytesIO

import pyrogram
from assemblyai import Transcript
from gspread import Spreadsheet
from loguru import logger
from peewee import fn
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import config as cfg
from data.models import User, UserMode, Mode, Transaction, Task
from helpers.db_helpers import create_mode_from_json
from integrations.gs_api import sheets
from misc.files import delete_file
from modules.assembly import Assembly
from modules.json_processor.struct_checkers import get_dict_from_json
from modules.report_generator import ReportGenerator
from telegram_bot.helpers import markup, txt
from telegram_bot.helpers.filters import admin_filter
from telegram_bot.helpers.tg_data_classes import StartData


def create_default_mode(db_user, sheet) -> Mode:
    """
    Создание базового режима
    """
    logger.info(f"Создаю базовый режим для tg_id: {db_user.tg_id}")

    default_full_json = get_dict_from_json(cfg.DEFAULT_JSON_PATH)
    mode_id = f"default{db_user.tg_id}"

    db_mode: Mode = create_mode_from_json(default_full_json, sheet.id, mode_id)

    return db_mode


def create_user_mode(db_user, db_mode) -> UserMode:
    """
    Привязка Mode и User к UserMode
    """
    logger.info(f"Создаю базовый UserMode для tg_id: {db_user.tg_id}")
    return UserMode.create(
        user=db_user,
        mode=db_mode
    )


def register_new_user(cli: Client, db_user: User):
    """
    Регистрация нового пользователя
    """
    logger.info(f"Зарегистрировал нового пользователя, tg_id: {db_user.tg_id}")

    # Создание Google таблицы
    m: Message = cli.send_message(db_user.tg_id, "Настраиваю вашего бота")
    m2: Message = cli.send_message(db_user.tg_id, "⏳")
    sheet: Spreadsheet = sheets.silent_create_default_spreadsheet(db_user)
    cli.delete_messages(db_user.tg_id, [m.id, m2.id])

    # Создание базового режима
    db_mode = create_default_mode(db_user, sheet)
    # Привязка базового режима к UserMode
    create_user_mode(db_user, db_mode)

    # БД
    db_user.mode_id = db_mode.mode_id  # Активный режим
    db_user.seconds_balance = cfg.FREE_SECONDS  # Начальный баланс минут
    db_user.save()

    # Создание транзакции
    transaction = Transaction.create(
        user=db_user,
        payment_sum=0,
        payment_currency='RUB',
        minutes=30,  # Бесплатные 30 минут
        payment_type='balance',
        payment_description='Initial free balance'
    )
    logger.info(f"Создал транзакцию: {transaction.id}")

    # Приветственная цепочка
    cli.send_message(db_user.tg_id, txt.first_message)
    cli.send_chat_action(db_user.tg_id, enums.ChatAction.TYPING)
    time.sleep(4)
    cli.send_message(db_user.tg_id, txt.free_minutes_present)

    return db_user


def handle_activation(message: Message, data_from_button, db_user: User):
    """
    Активация режима для пользователя по ссылке вида /start?data=....
    """
    mode_id = data_from_button.split("_")[1]

    # Получаем Mode
    db_mode: Mode = Mode.get_or_none(mode_id=mode_id)
    if not db_mode:
        logger.error(f"Режим c mode_id {mode_id} не найден в БД")
        return False

    # Обновляем UserMode
    user_mode: UserMode = UserMode.get_or_none(mode=db_mode)
    if not db_mode:
        logger.error(f"UserMode tg_id: {db_user.tg_id}, mode_id: {mode_id} не найден в БД")
        return False
    user_mode.user = db_user
    user_mode.save()

    # Устанавливаем пользователю активный режим бота
    db_user.mode_id = mode_id
    db_user.save()

    # Уведомляем пользователя об активации режима
    message.reply(txt.mode_activated(db_mode), disable_web_page_preview=True)

    return True


def handle_get_transcript(cli, data_from_button, db_user):
    """
    Получить транскрибацию звонка по ссылке
    """
    logger.info(f"Выгружаю транскрибацию звонка по ссылке из отчета")
    m = cli.send_message(db_user.tg_id, "⏳ Выгружаю транскрибацию звонка")

    transcript_id = data_from_button.split("_")[1]
    transcript: Transcript = Assembly(None).get_transcript_by_id(transcript_id)
    report_generator = ReportGenerator(db_user, transcript)
    txt_report_path = report_generator.generate_txt_report(add_analyze_data=False)
    cli.send_document(db_user.tg_id, txt_report_path)

    delete_file(txt_report_path)
    m.delete()


def send_message_with_cabinet(cli: Client, db_user: User):
    """
    Отправка сообщения "Личный кабинет"
    """
    return cli.send_message(db_user.tg_id, txt.cabinet(db_user),
                            reply_markup=markup.modes_markup(db_user),
                            disable_web_page_preview=True)


def handle_referral(cli: Client, message: Message, start_data, created: bool, db_user: User):
    """
    Обработка реферальной ссылки
    """
    if not created:
        return send_message_with_cabinet(cli, db_user)
    else:
        logger.info(f"Обрабатываю реферальную ссылку: {start_data}")

    # Парсинг параметров реферальной ссылки в словарь
    ref_dict = {}
    ref_params = start_data.split("__")
    for param in ref_params:
        try:
            key, value = param.split("_")
            ref_dict[key] = value
        except:
            continue

    # Запись реферала в БД
    bonus_from_tg_id = int(ref_dict.get(StartData.bonus_from, 0))
    parent_user: User = User.get_or_none(tg_id=bonus_from_tg_id)
    if not parent_user:
        return logger.error(f"Parent Пользователь с tg_id: {bonus_from_tg_id} не найден в БД")
    db_user.invited_by = parent_user.tg_id
    db_user.save()

    # Отчет по умолчанию
    default_mode_id = ref_dict.get(StartData.default_mode, None)
    if default_mode_id:
        default_mode: Mode = Mode.get_or_none(mode_id=default_mode_id)
        if not default_mode:
            return logger.error(f"Несуществующий ID отчета в реф ссылке. Mode_id '{default_mode_id}' не найден в БД")
        else:
            create_user_mode(db_user, default_mode)
            db_user.mode_id = default_mode.mode_id
            db_user.save()
            message.reply(txt.mode_activated(default_mode))

    # Уведомляем владельца реф ссылки о регистрации реферала
    cli.send_message(parent_user.tg_id, txt.referral_registered(message))


@Client.on_message(~filters.bot & filters.command("start"))
def start_cmd(cli: Client, message: Message):
    """
    Запуск бота /start
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")
    tg_id = message.from_user.id
    db_user, created = User.get_or_create(tg_id=tg_id)

    # Регистрация нового пользователя
    if created:
        db_user = register_new_user(cli, db_user)
        cli.send_message(cfg.ADMIN_CHAT_ID,
                         f"➕ Новый пользователь\n╟ @{message.from_user.username}\n╚ tg_id: {db_user.tg_id}")
    else:
        if not len(message.command) > 1:
            # Личный кабинет
            send_message_with_cabinet(cli, db_user)

    # Входящая команда
    if len(message.command) > 1:
        start_data = message.command[1]
        if "activate" in start_data:
            if not handle_activation(message, start_data, db_user):
                message.reply("Какая-то ошибка. Обратитесь к администратору @gorbunov")
        elif StartData.get_transcript in start_data:
            handle_get_transcript(cli, start_data, db_user)
        elif StartData.bonus_from in start_data:
            handle_referral(cli, message, start_data, created, db_user)

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("id"))
def id_cmd(cli: Client, message: Message):
    text = f"tg_id: {message.from_user.id}\nchat__id: {message.chat.id}"
    cli.send_message(message.chat.id, text, reply_markup=markup.with_close_btn())

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("partner"))
def partner_cabinet_cmd(cli: Client, message: Message):
    """
    Выгрузка лидов из БД бота в Гугл таблицу
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    db_user = User.get_or_none(tg_id=message.from_user.id)
    if db_user:
        cli.send_message(message.chat.id, txt.partner_cabinet(db_user), disable_web_page_preview=True)

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("get_transcripts"))
def get_transcripts_cmd(cli: Client, message: Message):
    """
    Получение файла с транскрибацией звонков.
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    db_user = User.get_or_none(tg_id=message.from_user.id)

    args = message.text.split()

    if len(args) > 3:
        message.reply("Формат команды: /get_transcripts date_from date_to")
        return None

    # Парсинг даты ОТ.
    if len(args) > 1:
        try:
            date_from = datetime.datetime.strptime(args[1], '%d.%m.%Y').date()
        except ValueError:
            message.reply("Неверный формат даты <b>date_from</b>. Формат: ДД.ММ.ГГГГ.")
            return None
    else:
        date_from = None

    # Парсинг даты ДО.
    if len(args) > 2:
        try:
            date_to = datetime.datetime.strptime(args[2], '%d.%m.%Y').date()
        except ValueError:
            message.reply("Неверный формат даты <b>date_to</b>. Формат: ДД.ММ.ГГГГ.")
            return None
    else:
        date_to = None

    cli.send_message(db_user.tg_id, 'Получаю транскрипты... Ожидайте.')
    cli.send_chat_action(db_user.tg_id, enums.ChatAction.UPLOAD_DOCUMENT)

    tasks = Task.select().where((Task.user == db_user) & (Task.transcript_id.is_null(False)))
    if date_from:
        tasks = tasks.where(fn.date_trunc('day', Task.created) >= date_from)
    if date_to:
        tasks = tasks.where(fn.date_trunc('day', Task.created) <= date_to)

    transcript_ids = [x.transcript_id for x in tasks.select(Task.transcript_id)][:cfg.MAX_TRANSCRIPTS_TO_SEND]
    transcripts = list(Assembly(None).get_transcript_list_by_ids(transcript_ids))

    if not transcripts:
        cli.send_message(db_user.tg_id, 'Транскрипты не найдены.')
    else:
        txt_report = ''
        report_generator = ReportGenerator(db_user)
        for transcript in transcripts:
            txt_report += report_generator.generate_transcript(transcript=transcript, add_header=True)

        with BytesIO(txt_report.encode('utf-8')) as f:
            cli.send_document(db_user.tg_id, f, file_name='transcripts.txt')

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & admin_filter & filters.command("activate_mode"))
def activate_mode_cmd(cli: Client, message: Message):
    """
    Обработчик команды /activate_mode tg_id mode_id
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    args = message.text.split()

    if len(args) != 3:
        return message.reply("Формат команды: /activate_mode tg_id mode_id")

    try:
        telegram_id = int(args[1])
        mode_id = args[2]
    except Exception:
        return message.reply("Неправильный формат tg_id или mode_id")

    db_user: User = User.get_or_none(tg_id=telegram_id)
    if not db_user:
        return message.reply(f"Пользователь с tg_id {telegram_id} не найден в БД.")

    db_mode: Mode = Mode.get_or_none(mode_id=mode_id)
    if not db_mode:
        return message.reply(f"Режим с mode_id {mode_id} не найден в БД.")

    user_mode: UserMode = UserMode.get_or_none(mode=db_mode)
    if not user_mode:
        return message.reply(f"UserMode для tg_id: {telegram_id}, mode_id: {mode_id} не найден в БД.")

    user_mode.user = db_user
    user_mode.save()

    db_user.mode_id = mode_id
    db_user.save()

    cli.send_message(telegram_id, txt.mode_activated(db_mode), disable_web_page_preview=True, disable_notification=True)
    message.reply(txt.mode_activated_admin_msg(db_mode, telegram_id), disable_web_page_preview=True)

    raise pyrogram.StopPropagation
