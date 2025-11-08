import time
from typing import Optional

import pyrogram
from assemblyai import Transcript
from loguru import logger
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import config as cfg
from data.models import User, UserMode, Mode, Transaction, Company
from helpers.db_helpers import create_default_telegram_report
from integrations.gs_api import sheets
from misc.files import delete_file
from modules.assembly import Assembly
from modules.report_generator import ReportGenerator
from telegram_bot.helpers import markup, txt
from telegram_bot.helpers.crm import create_bitrix_contact_and_deal
from telegram_bot.helpers.filters import admin_filter
from telegram_bot.helpers.tg_data_classes import StartData


def get_or_register_telegram_user(
        tg_id: int,
        username: Optional[str] = None,
        phone_number: Optional[str] = None,
        full_name: Optional[str] = None,
        cli: Optional[Client] = None,
):
    """
    Создает или возвращает из базы данных пользователя с указанным tg_id.
    Для нового пользователя также создаются: компания, Гугл Таблица, интеграция, отчет со стандартными колонками.
    """
    db_user, created = User.get_or_create(tg_id=tg_id, defaults={'full_name': full_name,
                                                                 'tg_username': username})

    # Если пользователь уже существует в базе, то возвращаем его без дополнительных действий.
    if not created:
        return db_user, created

    logger.info(f"Зарегистрировал нового пользователя, tg_id: {db_user.tg_id}, user_id: {db_user.id}")

    # Создание Google таблицы
    if cli is not None:
        m: Message = cli.send_message(db_user.tg_id, "Настраиваю вашего бота")
        m2: Message = cli.send_message(db_user.tg_id, "⏳")
    sheet = sheets.silent_create_default_spreadsheet(db_user)
    if cli is not None:
        cli.delete_messages(db_user.tg_id, [m.id, m2.id])

    # Создаем или находим компанию пользователя.
    company, _ = Company.get_or_create(name=f'tg_id_{db_user.tg_id}',
                                       defaults={'seconds_balance': cfg.FREE_MINUTES * 60})
    db_user.company = company
    db_user.company_role = Company.Roles.ADMIN
    logger.info(f'Связали пользователя с его компанией, company ID: {company.id}')

    db_user.save()

    create_default_telegram_report(db_user, sheet.id)

    # Создание транзакции
    transaction = Transaction.create(
        company=db_user.company,
        user=db_user,
        payment_sum=0,
        payment_currency='RUB',
        minutes=30,  # Бесплатные 30 минут
        payment_type=Transaction.PaymentType.DEMO,
        description='Initial free balance'
    )
    logger.info(f"Создал транзакцию: {transaction.id}")

    # Если у пользователя указан username в Telegram,
    # то создаем карточку контакта и сделки в Битриксе Речки.
    if username:
        logger.info(f'Создаем Контакт и Сделку в Битрикс для пользователя Telegram tg_id={db_user.tg_id=}.')
        try:
            contact_id, deal_id = create_bitrix_contact_and_deal(db_user,
                                                                 username,
                                                                 phone_number=phone_number,
                                                                 raise_on_exists=True)
        except Exception as ex:
            logger.error(f'Не удалось создать сделку или контакт в Битрикс24 для '
                         f'пользователя Telegram tg_id={db_user.tg_id=}. Ошибка: {ex}')
        else:
            logger.info(f'Созданы карточки Контакта (ID {contact_id}) и Сделки (ID {deal_id}) для '
                        f'пользователя Telegram tg_id={db_user.tg_id}.')

    if cli is not None:
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
    transcript: Transcript = Assembly('').get_transcript_by_id(transcript_id)
    report_generator = ReportGenerator(transcript=transcript)
    txt_report_path = report_generator.generate_txt_report()
    cli.send_document(db_user.tg_id, txt_report_path)

    delete_file(txt_report_path)
    m.delete()


def send_message_with_cabinet(cli: Client, db_user: User):
    """
    Отправка сообщения "Личный кабинет"
    """
    return cli.send_message(db_user.tg_id, txt.cabinet(db_user),
                            reply_markup=markup.reports_markup(db_user),
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

    db_user, created = get_or_register_telegram_user(tg_id,
                                                     username=message.from_user.username,
                                                     phone_number=message.from_user.phone_number,
                                                     cli=cli)

    if created:
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
