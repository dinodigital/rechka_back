import json
import urllib.parse
from datetime import datetime
from enum import Enum
from time import sleep
from typing import Optional

from loguru import logger

import peewee

import config.config as cfg
from modules.crypter import decrypt


class ReconnectPostgresqlDatabase(peewee.PostgresqlDatabase):

    def execute_sql(self, sql, params=None, commit=True):

        for attempt in range(3):  # 3 попытки переподключения
            try:
                return super().execute_sql(sql, params, commit)
            except peewee.OperationalError as oe:
                logger.error(f"Ошибка соединения с БД при выполнении запроса: {oe}")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при выполнении запроса к БД: {e}")
            self.close()
            # Пытаемся переподключиться
            try:
                self.connect(reuse_if_open=True)
                logger.info("Переподключение к базе данных успешно.")
            except Exception as reconnect_error:
                logger.error(f"Не удалось переподключиться к базе данных: {reconnect_error}")
            sleep(1)  # Пауза перед следующей попыткой

        logger.error("Не удалось выполнить запрос после 3 попыток.")
        raise RuntimeError("Не удалось подключиться к базе данных после 3 попыток")


# Инициализация базы данных
main_db = ReconnectPostgresqlDatabase(
    cfg.POSTGRES_DB,
    host=cfg.POSTGRES_HOST,
    port=cfg.POSTGRES_PORT,
    sslmode=cfg.POSTGRES_SSL_MODE,
    user=cfg.POSTGRES_USER,
    password=cfg.POSTGRES_PASSWORD,
    target_session_attrs='read-write',
)


class BaseModel(peewee.Model):
    class Meta:
        database = main_db

    data: str

    def get_data(self) -> dict:
        return json.loads(self.data)

    def get_filters(self) -> dict:
        data = self.get_data()
        return data.get('filters', {})

    def save_data(self, data_to_load: dict, update: bool = False):
        if update:
            data = self.get_data()
            data.update(data_to_load)
        else:
            data = data_to_load
        self.data = json.dumps(data)
        self.save()


class User(BaseModel):
    class Meta:
        table_name = 'app_user'

    created = peewee.DateTimeField(default=datetime.now)
    tg_id = peewee.BigIntegerField(default=None, null=True, unique=True)
    hashed_password = peewee.CharField(max_length=60, null=True)
    has_access = peewee.BooleanField(default=False, null=True)
    mode = peewee.TextField(default=None, null=True)
    payer_tg_id = peewee.BigIntegerField(default=None, null=True, help_text='None, если пользователь оплачивает со своего баланса.')
    seconds_balance = peewee.IntegerField(default=None, null=True)
    sheet_id = peewee.TextField(default=None, null=True)
    gmail = peewee.TextField(default=None, null=True)
    mode_id = peewee.TextField(default=None, null=True)
    invited_by = peewee.BigIntegerField(default=None, null=True)
    data = peewee.TextField(default=json.dumps({}))

    def get_active_mode(self) -> 'Mode':
        return Mode.get_or_none(mode_id=self.mode_id)

    def get_params(self):
        mode = self.get_active_mode()
        return mode.get_params() if mode else None

    def get_all_modes(self):
        return (Mode
                .select()
                .join(UserMode)
                .join(User)
                .where(User.id == self.id))

    def get_payer(self) -> 'User':
        """
        Возвращает пользователя, который оплачивает анализ звонков текущим пользователем.

        Это может быть как сам пользователь, анализирующий звонок,
        так и другой аккаунт, к балансу которого привязан текущий пользователь.
        """
        payer_tg_id = self.payer_tg_id if (self.payer_tg_id is not None) else self.tg_id

        user = User.get_or_none(User.tg_id == payer_tg_id)
        if user is None:
            user = User.get_or_none(User.id == self.id)

        return user

    def get_payer_balance(self):
        payer = self.get_payer()
        return payer.seconds_balance

    def minus_seconds_balance(self, seconds):
        # Минимум 60 секунд
        if seconds < 60:
            seconds = 60

        with main_db.atomic():
            payer_user = self.get_payer()
            payer_user.seconds_balance -= seconds
            payer_user.save()
            self.seconds_balance = payer_user.seconds_balance

        logger.info(f"Списал {seconds} секунд у {self.tg_id=} {payer_user.tg_id=}. "
                    f"Баланс: {self.seconds_balance} секунд")

    def add_seconds_balance(self, seconds):
        """
        Используется только для добавления секунд.
        Для вычитания используйте метод self.minus_seconds_balance.
        """
        # Минимум 60 секунд, потому что до возврата могли списать менее 60 секунд
        if seconds < 60:
            seconds = 60

        with main_db.atomic():
            user = User.select().where(User.id == self.id).get()
            user.seconds_balance += seconds
            user.save()
            self.seconds_balance = user.seconds_balance
        logger.info(f"Добавил {seconds} секунд у tg_id: {self.tg_id}. Баланс: {self.seconds_balance} секунд")


class Payment(BaseModel):
    created = peewee.DateTimeField(default=datetime.now)
    user = peewee.ForeignKeyField(User, backref="payments")
    invoice_number = peewee.TextField(default=None, null=True)
    invoice_sum = peewee.IntegerField(default=None, null=True)
    minutes = peewee.IntegerField(default=None, null=True)
    seconds = peewee.IntegerField(default=None, null=True)
    ppm_in_rub = peewee.FloatField(default=None, null=True)
    ppm_in_usd = peewee.FloatField(default=None, null=True)
    is_payed = peewee.IntegerField(default=0, null=True)
    data = peewee.TextField(default=json.dumps({}))


class Transaction(BaseModel):
    created = peewee.DateTimeField(default=datetime.now)
    user = peewee.ForeignKeyField(User, backref="transactions")
    payment_sum = peewee.IntegerField(null=True)
    payment_currency = peewee.CharField(max_length=10, null=True, default="RUB")
    minutes = peewee.IntegerField(null=True, default=0)
    payment_type = peewee.CharField(max_length=20)  # add_minutes, integration, other
    description = peewee.TextField(null=True)


class Mode(BaseModel):
    created = peewee.DateTimeField(default=datetime.now)
    name = peewee.TextField(default=None, null=True)
    mode_id = peewee.TextField(default=None, null=True)
    params = peewee.TextField(default=None, null=True)
    sheet_id = peewee.TextField(default=None, null=True)
    sheet_url = peewee.TextField(default=None, null=True)
    insert_row = peewee.IntegerField(default=3, null=True)
    gmail = peewee.TextField(default=None, null=True)
    tg_link = peewee.TextField(default=None, null=True)
    full_json = peewee.TextField(default=None, null=True)
    data = peewee.TextField(default=json.dumps({}))

    def get_params(self):
        return json.loads(self.params)

    def get_full_json(self):
        return json.loads(self.full_json)

    def update_params(self, params: dict):
        self.params = json.dumps(params)
        self.save()
        return self


class Task(BaseModel):

    class StatusChoices:
        # Возможные значения для поля status.
        IN_PROGRESS = 'in_progress'
        DONE = 'done'
        ERROR = 'error'
        CANCELLED = 'cancelled'
        choices = (
            (IN_PROGRESS, IN_PROGRESS),
            (DONE, DONE),
            (ERROR, ERROR),
            (CANCELLED, CANCELLED),
        )

    created = peewee.DateTimeField(default=datetime.now)
    user = peewee.ForeignKeyField(User, backref="tasks")
    transcript_id = peewee.TextField(default=None, null=True)
    transcript_model = peewee.TextField(default=None, null=True)
    analyze_id = peewee.TextField(default=None, null=True)
    analyze_model = peewee.TextField(default=None, null=True)
    analyze_data = peewee.TextField(default=None, null=True)
    analyze_input_tokens = peewee.IntegerField(default=None, null=True)
    analyze_output_tokens = peewee.IntegerField(default=None, null=True)
    assembly_duration = peewee.IntegerField(default=None, null=True)
    initial_duration = peewee.IntegerField(default=None, null=True)
    duration_sec = peewee.IntegerField(default=None, null=True)
    calculated_duration = peewee.IntegerField(default=None, null=True)
    file_url = peewee.TextField(default=None, null=True)
    data = peewee.TextField(default=json.dumps({}))
    minus_balance_sec = peewee.IntegerField(default=None, null=True)
    status = peewee.TextField(choices=StatusChoices.choices, default=StatusChoices.IN_PROGRESS)
    step = peewee.TextField(default=None, null=True)
    sheet_id = peewee.TextField(default=None, null=True)
    uploaded_data = peewee.TextField(default=None, null=True)
    error_details = peewee.TextField(default=None, null=True)
    mode = peewee.ForeignKeyField(Mode, backref="modes", null=True)

    def get_status_data(self) -> dict:
        data = self.get_data()

        result = {
            'account_id': data.get('account_id'),
            'telegram_id': data.get('telegram_id'),
            'task_id': data.get('task_id'),
            'call_id': data.get('call_id'),
            'report_status': data.get('report_status'),
            'status_message': data.get('status_message'),
            'call_report': data.get('call_report'),
            'transcript': data.get('transcript'),
        }

        task_settings = data.get('settings', {})
        task_result = data.get('result', {})

        if task_settings.get('advance_transcript'):
            result['advance_transcript_data'] = task_result.get('advance_transcript_data')

        return result


class UserMode(BaseModel):
    user = peewee.ForeignKeyField(User, backref='modes', default=None, null=True)
    mode = peewee.ForeignKeyField(Mode, backref='users', default=None, null=True)


class Integration(BaseModel):
    """
    Общая модель для всех интеграций.
    """
    created = peewee.DateTimeField(default=datetime.now)
    user = peewee.ForeignKeyField(User, backref='integrations', default=None, null=True)
    service_name = peewee.TextField(default=None, null=True)
    account_id = peewee.TextField(default=None, null=True)
    data = peewee.TextField(default=None, null=True)

    def has_amo_access_token(self) -> bool:
        """
        Используется только для интеграций amoCRM.
        Имеется ли в `data` токен доступа.
        """
        access = json.loads(self.data).get('access')
        return access and access.get('access_token')

    def get_decrypted_access_field(self, field_name: str, allow_empty: bool = False) -> str:
        """
        Возвращает дешифрованное значение поля field_name из self.data['access'].

        Аргумент allow_empty:
        1) True – вернуть пустую строку для пустого зашифрованного значения.
        2) False – будет вызвано исключение, если зашифрованное сообщение пусто.

        Примеры:

            1. Получить webhook_url для Bitrix24 (self.data['access']['webhook_url']):
                get_decrypted_access_field('webhook_url')

            2. Получить access_token для AmoCRM (self.data['access']['access_token']):
                get_decrypted_access_field('access_token', allow_empty=True)
                Если access_token в интеграции задан пустым, то метод вернет пустую строку,
                так как allow_empty is True.
        """
        data = self.get_data()
        encrypted_value = data['access'][field_name]
        if not encrypted_value and allow_empty:
            return ''
        decrypted_value = decrypt(encrypted_value, cfg.FERNET_KEY)
        return decrypted_value


class CallDownload(BaseModel):
    call_id = peewee.CharField(max_length=255, unique=True, verbose_name="ID звонка")
    status = peewee.CharField(max_length=20, default="failed", verbose_name="Статус загрузки")
    webhook = peewee.CharField(max_length=255, verbose_name="Вебхук", null=True)
    request_data = peewee.TextField(null=True, verbose_name="Данные запроса")
    retry_count = peewee.IntegerField(default=0, verbose_name="Количество попыток")
    last_attempt = peewee.DateTimeField(null=True, verbose_name="Время последней попытки")
    timestamp = peewee.DateTimeField(default=datetime.now, verbose_name="Время первой попытки")
    api_router = peewee.CharField(max_length=255, verbose_name="API роутер", null=True)

    @classmethod
    def create_or_update_from_webhook(
            cls,
            call_id,
            body_str,
            webhook_url,
            api_router: Optional[str] = None,
    ) -> 'CallDownload':

        obj = cls.get_or_none(cls.call_id == call_id)

        if obj is None:
            obj = cls.create(
                call_id=call_id,
                webhook=webhook_url,
                request_data=body_str,
                api_router=api_router,
            )
            logger.info(f'Bitrix24: Задание на скачивание сохранено в БД. Call ID: {call_id}')
        else:
            obj.retry_count = obj.retry_count + 1
            obj.last_attempt = datetime.now()
            obj.status = 'failed'
            obj.save()
            logger.info(f'Bitrix24: Задание на скачивание обновлено в БД. Call ID: {call_id}')

        return obj


class CallDownloadAMO(BaseModel):
    account_id = peewee.IntegerField(verbose_name="ID аккаунта")
    entity_id = peewee.CharField(max_length=255, verbose_name="ID entity")
    entity_name = peewee.CharField(max_length=255, verbose_name="Имя entity")
    status = peewee.CharField(max_length=20, default="failed", verbose_name="Статус загрузки")
    webhook = peewee.CharField(max_length=255, verbose_name="Вебхук", null=True)
    request_data = peewee.TextField(null=True, verbose_name="Данные запроса")
    retry_count = peewee.IntegerField(default=0, verbose_name="Количество попыток")
    last_attempt = peewee.DateTimeField(null=True, verbose_name="Время последней попытки")
    timestamp = peewee.DateTimeField(default=datetime.now, verbose_name="Время первой попытки")
    date_create = peewee.DateTimeField(verbose_name="Время создания звонка", null=True)

    @classmethod
    def create_or_update_from_webhook(
            cls,
            webhook,
            form_data,
            add_pipeline_and_status_names
    ) -> 'CallDownloadAMO':

        obj = cls.get_or_none((cls.entity_id == webhook.element_id) & (cls.date_create == webhook.date_create))

        if obj is None:
            body_str = urllib.parse.urlencode(dict(form_data), doseq=True)
            obj = cls.create(
                account_id=webhook.account_id,
                entity_id=webhook.element_id,
                entity_name=webhook.entity,
                webhook='/amo_webhook/v2' if add_pipeline_and_status_names else '/amo_webhook',
                request_data=body_str,
                date_create=webhook.date_create,
            )
        else:
            obj.retry_count = obj.retry_count + 1
            obj.last_attempt = datetime.now()
            obj.status = 'failed'
            obj.save()

        logger.info(f'AmoCRM: Звонок еще не загрузился в AMO. '
                    f'Задание на скачивание сохранено в БД. Entity ID: {webhook.element_id}.')

        return obj


class SipuniCall(BaseModel):
    call_id = peewee.CharField(max_length=255, verbose_name="ID звонка")
    account_id = peewee.CharField(max_length=255, verbose_name="ID клиента")
    created = peewee.DateTimeField(verbose_name="Время звонка")
    timestamp = peewee.DateTimeField(default=datetime.now, verbose_name="Время создания")


class BeelineCall(BaseModel):
    call_id = peewee.CharField(max_length=255, verbose_name="ID звонка")
    external_id = peewee.CharField(max_length=255, verbose_name="External ID звонка")
    phone = peewee.CharField(max_length=255, verbose_name="Телефон")
    direction = peewee.CharField(max_length=255, verbose_name="Направление")
    duration = peewee.IntegerField(verbose_name="Длительность")
    file_size = peewee.IntegerField(verbose_name="Размер аудиофайла")
    account_id = peewee.CharField(max_length=255, verbose_name="ID клиента")
    created = peewee.DateTimeField(verbose_name="Время звонка")
    timestamp = peewee.DateTimeField(default=datetime.now, verbose_name="Время создания")


class Report(BaseModel):
    created = peewee.DateTimeField(default=datetime.now)
    name = peewee.TextField(null=False)  # Название отчёта
    priority = peewee.IntegerField(default=10)  # Приоритет отчёта
    integration = peewee.ForeignKeyField(Integration, backref="reports", null=False)  # Связь с интеграцией
    mode = peewee.ForeignKeyField(Mode, backref="reports", null=False)  # Связь с Mode (может быть несколько)
    # sheet_id = peewee.TextField(null=True)  # ID Google-таблицы
    # sheet_url = peewee.TextField(null=True)  # URL Google-таблицы
    # worksheet_id = peewee.TextField(null=True)  # ID листа в таблице
    settings = peewee.TextField(default=json.dumps({}))  # Настройки CRM для отчёта
    filters = peewee.TextField(default=json.dumps({}))  # Фильтры для отчёта
    crm_data = peewee.TextField(default=json.dumps({}))  # Дополнительные данные для отчёта
    active = peewee.BooleanField(default=True)

    class Meta:
        table_name = 'report'  # Название таблицы в базе данных

    def get_report_filters(self) -> dict:
        return json.loads(self.filters)

    def get_report_settings(self) -> dict:
        return json.loads(self.settings)

    def get_report_crm_data(self) -> dict:
        return json.loads(self.crm_data)


class IntegrationServiceName(str, Enum):
    """
    Названия типов интеграций.

    Модель для всех интеграций общая.
    Различие интеграций разных сервисов осуществляется через поле `Integration.service_name`,
    которое может принимать одно из нижеследующих значений.
    """
    AMOCRM = 'amocrm'
    BITRIX24 = 'bitrix24'
    BEELINE = 'beeline'
    SIPUNI = 'sipuni'
    CUSTOM = 'custom'


def create_db_tables_if_not_exists() -> bool:
    logger.info(f"Проверяем и при необходимости создаем таблицы в БД.")
    with main_db:
        main_db.create_tables([
            User,
            Task,
            Payment,
            Mode,
            UserMode,
            Integration,
            CallDownload,
            CallDownloadAMO,
            SipuniCall,
            Transaction,
            BeelineCall,
            Report
        ])
    return True
