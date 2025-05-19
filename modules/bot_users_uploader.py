from pyrogram import Client
from loguru import logger
from data.models import User
from helpers.tg_helpers import get_user_info
from integrations.gs_api.syncer import sync_leads_to_sheet
from config import config as cfg


def sync_leads_to_google_sheets():
    """
    Выгрузка лидов из БД бота в Гугл таблицу с использованием отдельного инстанса клиента Telegram
    """
    # Создаем отдельный инстанс клиента Telegram
    app = Client(
        "sync_bot",
        api_id=cfg.BOT_API_ID,
        api_hash=cfg.BOT_API_HASH,
        bot_token=cfg.BOT_TOKEN
    )

    try:
        logger.info("Начиню выгрузку пользователей бота в Гугл таблицу")
        # Запускаем клиент
        app.start()

        # Получаем всех пользователей
        logger.info("Получаю пользователей бота")
        users = User.select()
        tg_ids = [user.tg_id for user in users]

        # Получаем информацию о пользователях
        logger.info("Получаю информацию о пользователях")
        users_info = get_user_info(app, tg_ids)

        # Синхронизируем данные с Google Sheets
        logger.info("Синхронизирую данные с Google Sheets")
        updated, added = sync_leads_to_sheet(users, users_info)

        logger.info(f"Синхронизация завершена успешно\nОбновлено строк: {updated}\nДобавлено новых строк: {added}")

    except Exception as e:
        logger.error(f"Ошибка при синхронизации: {str(e)}")

    finally:
        # Останавливаем клиент
        app.stop()

