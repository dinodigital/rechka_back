import os
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
ROOT_DIR = Path(__file__).resolve().parent.parent
GOOGLE_PATH = os.path.join(ROOT_DIR, 'config/cr.json')
DEFAULT_JSON_PATH = os.path.join(ROOT_DIR, 'config/default.json')
DOWNLOADS_PATH = os.path.join(ROOT_DIR, 'downloads/')
os.makedirs(DOWNLOADS_PATH, exist_ok=True)

# Путь к логам Python-приложений.
LOGS_DIR = os.path.join(ROOT_DIR, 'log/')
LOG_PATH = os.path.join(LOGS_DIR, 'fastapi.log')
os.makedirs(LOGS_DIR, exist_ok=True)

# База данных
POSTGRES_DB = os.environ['POSTGRES_DB']
POSTGRES_HOST = os.environ['POSTGRES_HOST']
POSTGRES_PORT = os.environ['POSTGRES_PORT']
POSTGRES_USER = os.environ['POSTGRES_USER']
POSTGRES_PASSWORD = os.environ['POSTGRES_PASSWORD']
POSTGRES_SSL_MODE = os.environ['POSTGRES_SSL_MODE']


REDIS_URL = os.environ.get("CELERY_BROKER")

# Безопасность
FERNET_KEY = os.environ.get('FERNET_KEY')

# Аутентификация, пароли
SECRET_KEY = os.environ['SECRET_KEY']
CRYPTO_ALGORITHM = os.environ.get('CRYPTO_ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = os.environ.get('ACCESS_TOKEN_EXPIRE_MINUTES', 30)


# Google sheet
SHEETS_TEMPLATE_FILE_ID = os.environ.get('SHEETS_TEMPLATE_FILE_ID')
CLIENT_TEMPLATE_ID = os.environ.get('CLIENT_TEMPLATE_ID')
LEAD_SHEET_ID = os.environ.get('LEAD_SHEET_ID')
ANALYTICS_SHEET_ID = os.environ.get('ANALYTICS_SHEET_ID')

# Telegram
BOT_LINK = os.environ.get('BOT_LINK')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
BOT_API_ID = os.environ.get('BOT_API_ID')
BOT_API_HASH = os.environ.get('BOT_API_HASH')
RECHKA_CHAT_USERNAME = os.environ.get('RECHKA_CHAT_USERNAME')
# Максимальное количество транскриптов, которые пользователь может получить в боте за раз.
MAX_TRANSCRIPTS_TO_SEND = os.environ.get('MAX_TRANSCRIPTS_TO_SEND', 100)

# Нейросети
ASSEMBLYAI_KEY = os.environ.get('ASSEMBLYAI_KEY')
QUESTION_MODELS_LIST = ['default', 'basic']
TASK_MODELS_LIST = ["anthropic/claude-3-5-sonnet", "anthropic/claude-3-haiku"]

# Robokassa
ROBOKASSA_MERCHANT_LOGIN = os.environ.get('ROBOKASSA_MERCHANT_LOGIN')
ROBOKASSA_MERCHANT_PASS_1 = os.environ.get('ROBOKASSA_MERCHANT_PASS_1')
ROBOKASSA_MERCHANT_PASS_2 = os.environ.get('ROBOKASSA_MERCHANT_PASS_2')
SERVER_LINK = os.environ.get('SERVER_LINK')
ROBOKASSA_IS_TEST = os.environ.get('ROBOKASSA_IS_TEST')

# Битрикс24.
BITRIX24_RECHKA_INTEGRATION_ID = os.environ['BITRIX24_RECHKA_INTEGRATION_ID']
BITRIX24_NEW_TG_USER_PIPELINE_ID = os.environ.get('BITRIX24_NEW_TG_USER_PIPELINE_ID')
BITRIX24_NEW_TG_USER_STAGE_ID = os.environ.get('BITRIX24_NEW_TG_USER_STAGE_ID')
BITRIX24_NEW_TG_USER_SOURCE_ID = os.environ.get('BITRIX24_NEW_TG_USER_SOURCE_ID')
BITRIX24_CONTACT_REFERRER_FIELD_NAME = os.environ.get('BITRIX24_CONTACT_REFERRER_FIELD_NAME')
BITRIX24_CONTACT_TG_ID_FIELD_NAME = os.environ['BITRIX24_CONTACT_TG_ID_FIELD_NAME']

# Общие настройки
BOT_APP_NAME = 'My bot'
SENDER_APP_NAME = 'My sender'
ADMINS = [int(x.strip()) for x in os.environ['ADMINS'].split(',')]
ERROR_CHAT_ID = os.environ.get('ERROR_CHAT_ID')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')
TIME_ZONE = 'Europe/Moscow'
# Сохранять транскрипт текстом в Google Sheets.
SAVE_TRANSCRIPT_AS_TEXT: bool = os.environ.get('SAVE_TRANSCRIPT_AS_TEXT', 'False').lower() in ('true', '1', 't')

# Стартовые настройки продукта
FREE_MINUTES = 30
FREE_SECONDS = FREE_MINUTES * 60

# ЦЕНЫ
PRICE_PER_MINUTE_IN_RUB = 6
PRICE_PER_MINUTE_IN_USD = 6/100

# Sentry
BOT_SENTRY_DSN = os.environ.get('BOT_SENTRY_DSN')
API_SENTRY_DSN = os.environ.get('API_SENTRY_DSN')

ENV = os.environ.get('ENV', 'local').lower().strip()
PRODUCTION = (ENV == 'production')

# SSL
SSL_KEYFILE_PATH = os.environ.get('SSL_KEYFILE_PATH')
SSL_CERTFILE_PATH = os.environ.get('SSL_CERTFILE_PATH')
SSL_KEYFILE_PASSWORD = os.environ.get('SSL_KEYFILE_PASSWORD')

FASTAPI_HTTPS_ONLY: bool = os.environ.get('FASTAPI_HTTPS_ONLY', 'False').lower() in ('true', '1', 't')
# Список доменов, которым разрешено делать запросы к Fastapi-серверу.
FASTAPI_CORS_ORIGINS: list = [
    x.strip() for x in os.environ.get('FASTAPI_CORS_ORIGINS', '').split(',') if x.strip()
]
