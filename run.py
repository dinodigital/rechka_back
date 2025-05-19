import signal
from loguru import logger
from peewee import InterfaceError
from time import sleep

from config import config
from data.models import create_db_tables_if_not_exists, main_db
from telegram_bot.apps import main_app


def stop_signal_handler(signum, frame):
    """
    Обработчик сигналов завершения.
    Закрывает соединение с базой данных и завершает работу программы.
    """
    logger.info('Завершение работы тг-бота. Закрываем соединение с БД.')
    main_db.close()
    exit(0)


def reconnect_to_db():
    """
    Восстанавливает соединение с базой данных, если оно было потеряно.
    """
    try:
        if not main_db.is_closed():
            main_db.close()
            logger.info("Закрываем неактивное соединение с базой данных.")

        main_db.connect()
        logger.info("Соединение с базой данных восстановлено (БОТ).")
    except Exception as e:
        logger.error(f"Ошибка при переподключении к БД: {e}")
        sleep(5)
        reconnect_to_db()


def run_bot():
    """
    Запуск Telegram бота с обработкой возможных ошибок.
    При возникновении ошибки автоматически перезапускает бота.
    """
    try:
        # Логирование запуска бота
        logger.info("Запускаю бота")
        main_app.run()
    except InterfaceError as interface_error:
        # Ошибка соединения с базой данных
        logger.error(f"[-] Соединение к БД закрыто. Детали: {interface_error}")
        reconnect_to_db()  # Восстановление соединения с БД
        run_bot()  # Рекурсивный вызов для перезапуска бота
    except Exception as e:
        # Любая другая ошибка
        logger.error(f"[-] Неожиданная ошибка: {e}. Перезапуск через 5 секунд...")
        sleep(5)  # Задержка перед перезапуском
        run_bot()  # Перезапуск бота


# Настройка обработки сигналов завершения
signal.signal(signal.SIGINT, stop_signal_handler)
signal.signal(signal.SIGTERM, stop_signal_handler)


# Основная точка входа
if __name__ == "__main__":
    # Проверка и создание таблиц в базе данных, если они не существуют
    create_db_tables_if_not_exists()

    # Конфигурация Sentry для отслеживания ошибок
    if config.BOT_SENTRY_DSN:
        logger.info("Configuring Sentry")
        import sentry_sdk
        sentry_sdk.init(
            dsn=config.BOT_SENTRY_DSN,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            environment=config.ENV,
        )

    # Запуск бота с возможностью перезапуска при ошибках
    run_bot()
