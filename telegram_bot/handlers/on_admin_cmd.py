import json
from io import BytesIO
from typing import Callable

import pyrogram
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message

from data.models import User, Integration, IntegrationServiceName
from helpers.tg_helpers import get_user_info
from integrations.amo_crm.amo_api_core import AmoApi
from integrations.bitrix.bitrix_api import Bitrix24
from integrations.gs_api.syncer import sync_leads_to_sheet
from telegram_bot.helpers import txt, markup
from telegram_bot.helpers.filters import admin_filter
from tools.commands import parse_bitrix_funnels_and_stages


@Client.on_message(~filters.bot & filters.command("add_minutes") & admin_filter)
def add_balance_cmd(cli: Client, message: Message):
    """
    Пополнение баланса пользователя.
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    args = message.text.split()

    if len(args) != 3:
        return message.reply("Неправильный формат команды.")

    try:
        user_id = int(args[1])
        minutes_to_add = int(args[2])
    except Exception:
        return message.reply("Неправильный формат чисел в tg_id или минутах.")

    db_user: User = User.get_or_none(tg_id=user_id)
    if not db_user:
        return message.reply(f"Пользователь с tg_id {user_id} не найден в БД.")

    if minutes_to_add > 0:
        db_user.add_seconds_balance(minutes_to_add * 60)
    else:
        db_user.minus_seconds_balance(minutes_to_add * 60)

    cli.send_message(db_user.tg_id, txt.admin_balance_added(minutes_to_add))
    message.reply(f"ID: {user_id}, BALANCE: +{minutes_to_add} min")

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("pay") & admin_filter)
def pay_test(cli: Client, message: Message):
    """
    Проверка платежа
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    message.reply("Тестовый боевой платеж", reply_markup=markup.pay_test_button(1))


@Client.on_message(~filters.bot & filters.command("sync") & admin_filter)
def sync_cmd(cli: Client, message: Message):
    """
    Выгрузка лидов из БД бота в Гугл таблицу
    """
    m: Message = cli.send_message(message.chat.id, "⏳")

    users = User.select()
    tg_ids = [user.tg_id for user in users]

    users_info = get_user_info(cli, tg_ids)
    updated, added = sync_leads_to_sheet(users, users_info)

    text = f"Обновлено строк: {updated}\nДобавлено новых строк: {added}"
    m.edit_text(text, reply_markup=markup.with_close_btn())

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("set_payer_tg_id") & admin_filter)
def set_payer_tg_id_cmd(cli: Client, message: Message):
    """
    Установка материнского баланса для пользователя.
    Формат:
        /set_payer_tg_id <user_tg_id> <payer_tg_id>
        <user_tg_id> – Telegram ID пользователя.
        <payer_tg_id> – Telegram ID пользователя с материнским балансом.
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    args = message.text.split()

    if len(args) != 3:
        message.reply("Формат команды: /set_payer_tg_id user_tg_id payer_tg_id")
        return None

    try:
        user_tg_id = int(args[1])
    except Exception:
        message.reply("Неправильный формат user_tg_id.")
        return None

    user = User.get_or_none(tg_id=user_tg_id)
    if user is None:
        message.reply(f"Не найден пользователь с tg_id {user_tg_id}.")
        return None
    
    try:
        payer_tg_id = int(args[2])
    except Exception:
        message.reply("Неправильный формат payer_tg_id.")
        return None

    payer = User.get_or_none(tg_id=payer_tg_id)
    if payer is None:
        message.reply(f"Не найден пользователь с tg_id {payer_tg_id}.")
        return None

    user.payer_tg_id = payer_tg_id
    user.save()

    logger.info(f'Материнский баланс для {user_tg_id} успешно установлен ({payer_tg_id}).')
    message.reply(f'Материнский баланс для {user_tg_id} успешно установлен ({payer_tg_id}).')

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command("remove_payer_tg_id") & admin_filter)
def remove_payer_tg_id_cmd(cli: Client, message: Message):
    """
    Сбрасывает материнский баланс для пользователя.
    Формат:
        /remove_payer_tg_id <user_tg_id>
        <user_tg_id> – Telegram ID пользователя, для которого нужно сбросить привязку к материнскому балансу.
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    args = message.text.split()

    if len(args) != 2:
        message.reply("Формат команды: /remove_payer_tg_id user_tg_id")
        return None

    try:
        user_tg_id = int(args[1])
    except Exception:
        message.reply("Неправильный формат user_tg_id.")
        return None

    user = User.get_or_none(tg_id=user_tg_id)
    if user is None:
        message.reply(f"Не найден пользователь с tg_id {user_tg_id}.")
        return None

    user.payer_tg_id = None
    user.save()

    logger.info(f'Материнский баланс для {user_tg_id} успешно сброшен.')
    message.reply(f'Материнский баланс для {user_tg_id} успешно сброшен.')

    raise pyrogram.StopPropagation


def process_integration_and_send_result(
        cli: Client,
        message: Message,
        bitrix_func: Callable,
        amo_func: Callable,
        command_name: str,
) -> None:
    """
    Возвращает данные из интеграции по переданному ID в args[1].
    Данные получаются функцией для соответствующего типа интеграции: bitrix_func или amo_func.
    """
    logger.info(f"tg_id: '{message.from_user.id}'  message: '{message.text}'")

    args = message.text.split()
    try:
        if len(args) != 2:
            raise ValueError
        integration_id = int(args[1])
    except (IndexError, ValueError):
        message.reply(f'Формат команды: /{command_name} integration_id')
        return None

    integration = Integration.get_or_none(Integration.id == integration_id)

    if integration is None:
        message.reply(f'Не удалось найти интеграцию с ID {integration_id}.')
        return None

    if integration.service_name == IntegrationServiceName.BITRIX24:
        data = bitrix_func(integration)

    elif integration.service_name == IntegrationServiceName.AMOCRM:
        data = amo_func(integration)

    else:
        message.reply(f'Неизвестный тип интеграции: {integration.service_name}.')
        return None

    if isinstance(data, str):
        result = data
        ext = '.txt'
    else:
        result = json.dumps(data, ensure_ascii=False, indent=1)
        ext = '.json'

    with BytesIO(result.encode('utf-8')) as f:
        cli.send_document(message.from_user.id, f, file_name=f'{command_name}_{integration_id}{ext}')

    logger.info(f'Отправили пользователю tg_id={message.from_user.id} '
                f'файл с результатом команды "/{command_name} {integration_id}".')

    raise pyrogram.StopPropagation


@Client.on_message(~filters.bot & filters.command('get_users') & admin_filter)
def get_integration_users_cmd(cli: Client, message: Message):
    """
    Выгрузка информации о пользователях для интеграции Bitrix24 или AmoCRM.
    """
    def bitrix_func(integration):
        bx24 = Bitrix24(integration.get_decrypted_access_field('webhook_url'))
        return bx24.get_users_as_text()

    def amo_func(integration):
        amo = AmoApi(integration)
        return amo.get_users_as_text()

    process_integration_and_send_result(cli, message, bitrix_func, amo_func, command_name='get_users')


@Client.on_message(~filters.bot & filters.command('get_statuses') & admin_filter)
def get_integration_statuses_cmd(cli: Client, message: Message):
    """
    Выгрузка ID воронок и этапов (статусов) для интеграции Bitrix24 или AmoCRM.
    """

    def bitrix_func(integration):
        return parse_bitrix_funnels_and_stages(integration.id)

    def amo_func(integration):
        amo = AmoApi(integration)
        return amo.get_pipelines_as_text()

    process_integration_and_send_result(cli, message, bitrix_func, amo_func, command_name='get_statuses')


@Client.on_message(~filters.bot & filters.command('get_fields') & admin_filter)
def get_integration_fields_cmd(cli: Client, message: Message):
    """
    Выгрузка кастомных полей сделки для интеграции Bitrix24 или AmoCRM.
    """
    def bitrix_func(integration):
        bx24 = Bitrix24(integration.get_decrypted_access_field('webhook_url'))
        return bx24.parse_bitrix_custom_fields()

    def amo_func(integration):
        amo = AmoApi(integration)
        return amo.get_leads_custom_fields()

    process_integration_and_send_result(cli, message, bitrix_func, amo_func, command_name='get_fields')

    raise pyrogram.StopPropagation
