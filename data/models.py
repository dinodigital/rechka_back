import json
import re
import urllib.parse
from copy import deepcopy
from datetime import datetime, timedelta
from enum import Enum
from functools import reduce
from json import JSONDecodeError
from operator import or_, and_
from time import sleep
from typing import Optional, Set

from gspread.urls import SPREADSHEET_DRIVE_URL
from loguru import logger

import peewee

import config.config as cfg
from misc.time import get_refresh_time
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

    def save_data(self, data_to_load: dict, update: bool = False):
        if update:
            data = self.get_data()
            data.update(data_to_load)
        else:
            data = data_to_load
        self.data = json.dumps(data)
        self.save()


class Company(BaseModel):
    """
    Компания объединяет нескольких пользователей.
    """
    class Meta:
        indexes = (
            (('name', 'firm_name'), True),
        )

    # Возможные роли пользователей внутри компании.
    class Roles(str, Enum):
        ADMIN = 'admin'
        USER = 'user'

    created = peewee.DateTimeField(default=datetime.now)
    name = peewee.CharField()
    firm_name = peewee.CharField(default='')
    seconds_balance = peewee.IntegerField(default=0)
    bitrix_company_id = peewee.CharField(default=None, null=True)

    def add_balance(
            self,
            seconds_to_add: int,
            **transaction_kwargs,
    ):
        """
        Если transaction_kwargs не переданы, транзакция не создается.
        """

        # Минимум 60 секунд.
        if abs(seconds_to_add) < 60:
            if seconds_to_add > 0:
                seconds_to_add = 60
            else:
                seconds_to_add = -60

        with main_db.atomic():

            # Блокируем строку для изменения другими транзакциями.
            company = Company.select().where(Company.id == self.id).for_update().get()

            if transaction_kwargs:
                rounded_minutes = seconds_to_add // 60
                transaction_kwargs.update({
                    'company': company,
                    'minutes': rounded_minutes,
                })
                transaction = Transaction.create(**transaction_kwargs)
            else:
                transaction = None

            if seconds_to_add != 0:
                initial_balance = company.seconds_balance

                Company.update(
                    seconds_balance=Company.seconds_balance + seconds_to_add
                ).where(Company.id == self.id).execute()
                updated_balance = Company.get(id=self.id).seconds_balance

                logger.info(f"Добавил {seconds_to_add} секунд компании ID: {company.id}. "
                            f"Баланс: {initial_balance} -> {updated_balance} секунд.")

        return transaction

    @staticmethod
    def transfer_balance(
            from_company: 'Company',
            to_company: 'Company',
            minutes_to_transfer: int,
    ):
        """
        Переводит баланс от одной компании другой, создает записи об этом в базе (Transaction).
        Обновляет балансы одной транзакцией. Если одной из компаний не удалось сменить баланс, второй тоже не меняется.
        """
        from_tr_kwargs = dict(payment_sum=0,
                              payment_currency='RUB',
                              payment_type=Transaction.PaymentType.ADMIN,
                              description='Transfer to another user')

        to_tr_kwargs = dict(payment_sum=0,
                            payment_currency='RUB',
                            payment_type=Transaction.PaymentType.ADMIN,
                            description='Transfer from another user')

        with main_db.atomic() as txn:
            try:
                # Предотвращение дедлока.
                if from_company.id < to_company.id:
                    from_company.add_balance(-minutes_to_transfer * 60, **from_tr_kwargs)
                    to_company.add_balance(minutes_to_transfer * 60, **to_tr_kwargs)
                else:
                    to_company.add_balance(minutes_to_transfer * 60, **to_tr_kwargs)
                    from_company.add_balance(-minutes_to_transfer * 60, **from_tr_kwargs)
            except Exception as ex:
                txn.rollback()
                logger.error(f'Ошибка при переводе средств от Company {from_company.id} '
                             f'к Company {to_company.id}: {type(ex)} {ex}')
                raise ex


class User(BaseModel):
    class Meta:
        table_name = 'app_user'

    created = peewee.DateTimeField(default=datetime.now)
    tg_id = peewee.BigIntegerField(default=None, null=True, unique=True)
    tg_username = peewee.CharField(default=None, null=True)
    hashed_password = peewee.CharField(max_length=60, null=True)
    seconds_balance = peewee.IntegerField(default=None, null=True)
    mode_id = peewee.TextField(default=None, null=True)
    invited_by = peewee.BigIntegerField(default=None, null=True)
    data = peewee.TextField(default=json.dumps({}))
    full_name = peewee.CharField(default=None, null=True)
    email = peewee.CharField(default=None, null=True)
    is_admin = peewee.BooleanField(default=False, verbose_name='Является ли администратором системы')

    company = peewee.ForeignKeyField(Company)
    company_role = peewee.TextField(default=Company.Roles.USER.value,
                                    choices=[(x.value, x.value) for x in Company.Roles],
                                    verbose_name='Роль в компании')

    def clean_email(self):
        if self.email is not None:
            email_regex = r'^[a-zA-Z][a-zA-Z0-9._%+-]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_regex, str(self.email)):
                raise ValueError('Некорректный формат e-mail')

    def save(self, *args, **kwargs):
        self.clean_email()
        return super().save(*args, **kwargs)

    def get_active_mode(self) -> 'Mode':
        return Mode.get_or_none(mode_id=self.mode_id)

    def get_all_modes(self):
        return (Mode
                .select()
                .join(UserMode)
                .join(User)
                .where(User.id == self.id))

    def get_seconds_balance(self) -> int:
        return self.company.seconds_balance

    def get_accessible_companies(
            self,
            company_id: Optional[int] = None,
            allow_company_user: Optional[bool] = False,
    ) -> peewee.ModelSelect:
        """
        Возвращает список ID компаний, к которым пользователь имеет доступ.

        Правила доступа:
        1. Системный администратор (user.is_admin is True):
           - Доступ ко всем компаниям в системе.
        2. Администратор компании (user.company_role == Company.Roles.ADMIN):
           - Доступ к своей компании (user.company).
           - Доступ к компаниям, где пользователь является интегратором.
        3. Обычный интегратор:
           - Доступ только к компаниям, где пользователь указан как интегратор
             (через модель `IntegratorCompany`).

        Аргументы:
            company_id (int):           Если передан, то проверяется доступ к конкретной компании.
                                        В ответ будет возвращена либо компания, либо пустой набор.
            allow_company_user (bool):  Разрешить ли пользователю доступ к компании, если
                                        он является ее участником, но не является ее администратором.

        Результат:
            peewee.ModelSelect: Компании, к которым пользователь имеет доступ.
        """
        companies = Company.select()

        # Системный администратор.
        if self.is_admin:
            if company_id is not None:
                companies = companies.where(Company.id == company_id)
            return companies

        accessible_company_ids = set()

        # Своя компания, если администратор.
        if (allow_company_user or self.company_role == Company.Roles.ADMIN) and self.company:
            accessible_company_ids.add(self.company.id)

        # Компании, в которых интегратор.
        integrator_company_ids = IntegratorCompany.get_integrator_companies(self)
        accessible_company_ids.update(integrator_company_ids)

        if company_id is not None:
            if company_id in accessible_company_ids:
                companies = companies.where(Company.id == company_id)
            else:
                companies = companies.where(0 == 1)
        else:
            companies = companies.where(Company.id.in_(accessible_company_ids))

        return companies


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
    class PaymentType(str, Enum):
        DEMO = 'demo'
        PAYMENT = 'payment'
        ADMIN = 'admin'

    created = peewee.DateTimeField(default=datetime.now)
    company = peewee.ForeignKeyField(Company, default=None, null=True)
    user = peewee.ForeignKeyField(User, backref='transactions', default=None, null=True)
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
    insert_row = peewee.IntegerField(default=3, null=True)
    tg_link = peewee.TextField(default=None, null=True)
    full_json = peewee.TextField(default=None, null=True)

    def get_params(self):
        return json.loads(self.params)

    def get_full_json(self):
        return json.loads(self.full_json)

    def update_params(self, params: dict):
        self.params = json.dumps(params)
        self.save()
        return self


class Integration(BaseModel):
    """
    Общая модель для всех интеграций.
    """
    created = peewee.DateTimeField(default=datetime.now)
    user = peewee.ForeignKeyField(User, backref='integrations', default=None, null=True)
    company = peewee.ForeignKeyField(Company, backref='integrations', default=None, null=True)
    service_name = peewee.TextField()
    account_id = peewee.TextField(unique=True)
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
        1) True – вернуть пустую строку для пустого или отсутствующего зашифрованного значения.
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
        encrypted_value = data['access'].get(field_name)
        if not encrypted_value and allow_empty:
            return ''
        decrypted_value = decrypt(encrypted_value, cfg.FERNET_KEY)
        return decrypted_value


class Deal(BaseModel):
    """
    Сделка. Связывает несколько звонков в рамках одной системы клиента.
    Пример использования: анализ звонка с учетом результатов анализа предыдущего звонка сделки.
    """
    created = peewee.DateTimeField(default=datetime.now)
    integration = peewee.ForeignKeyField(Integration, backref="deals")
    crm_id = peewee.CharField()


class Report(BaseModel):
    created = peewee.DateTimeField(default=datetime.now)
    active = peewee.BooleanField(default=False)
    is_archived = peewee.BooleanField(default=False)
    priority = peewee.IntegerField(default=10)  # Приоритет отчёта

    name = peewee.TextField()  # Название отчёта
    integration = peewee.ForeignKeyField(Integration, backref="reports")  # Связь с интеграцией
    mode = peewee.ForeignKeyField(Mode, backref="reports", default=None, null=True)  # Связь с Mode (может быть несколько)
    sheet_id = peewee.TextField(default=None, null=True)

    description = peewee.TextField(default='')
    settings = peewee.TextField(default=json.dumps({}))  # Настройки CRM для отчёта
    filters = peewee.TextField(default=json.dumps({}))  # Фильтры для отчёта
    crm_data = peewee.TextField(default=json.dumps({}))  # Дополнительные данные для отчёта
    final_model = peewee.CharField()
    context = peewee.TextField(null=True, verbose_name='Общий контекст')

    class Meta:
        table_name = 'report'  # Название таблицы в базе данных

    def clean(self):
        if self.final_model not in cfg.TASK_MODELS_LIST:
            raise ValueError('Неизвестная модель для анализа.')

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    @property
    def sheet_url(self) -> Optional[str]:
        """
        Создание ссылки на Гугл таблицу по sheet_id.
        """
        if (self.sheet_id is None
                or self.sheet_id == 'null' # если с фронта сохранили null.
        ):
            return None
        return SPREADSHEET_DRIVE_URL % self.sheet_id

    def get_report_filters(self) -> dict:
        return json.loads(self.filters)

    def get_report_settings(self) -> dict:
        return json.loads(self.settings)

    def get_report_crm_data(self) -> dict:
        return json.loads(self.crm_data)

    def get_ai_columns(self):
        """
        Возвращает активные AI-колонки отчета.
        """
        return (
            ModeQuestion
            .select()
            .where(ModeQuestion.report == self,
                   ModeQuestion.is_active == True,
                   ModeQuestion.calc_type == ModeQuestionCalcType.AI)
            .order_by(ModeQuestion.column_index.asc())
        )

    def get_custom_columns(self):
        """
        Возвращает активные кастомные колонки отчета.
        """
        return (
            ModeQuestion
            .select()
            .where(ModeQuestion.report == self,
                   ModeQuestion.is_active == True,
                   ModeQuestion.calc_type == ModeQuestionCalcType.CUSTOM)
            .order_by(ModeQuestion.column_index.asc())
        )


class IntegratorCompany(BaseModel):
    """
    Связь пользователя с компанией, в которой он является интегратором.
    """
    integrator = peewee.ForeignKeyField(User)
    company = peewee.ForeignKeyField(Company)

    @classmethod
    def get_integrator_companies(cls, user: User) -> Set[int]:
        company_ids = {
            obj.company.id
            for obj in cls.select(cls.company).where(cls.integrator == user)
        }
        return company_ids


class ActiveTelegramReport(BaseModel):
    """
    Активный отчет пользователя в Telegram.
    """
    user = peewee.ForeignKeyField(User, unique=True)
    report = peewee.ForeignKeyField(Report)


class RequestLog(BaseModel):
    """
    Запрос к FastAPI-приложению.
    """

    timestamp = peewee.DateTimeField(default=datetime.now)
    context_id = peewee.CharField(max_length=64, null=True)
    log = peewee.TextField(default='')

    method = peewee.CharField()
    path = peewee.CharField()
    headers = peewee.TextField()
    body = peewee.TextField(null=True)

    company = peewee.ForeignKeyField(Company, default=None, null=True)


class Task(BaseModel):
    class StatusChoices:
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
    user = peewee.ForeignKeyField(User, backref="tasks", default=None, null=True)
    deal = peewee.ForeignKeyField(Deal, null=True)
    mode = peewee.ForeignKeyField(Mode, null=True)
    report = peewee.ForeignKeyField(Report, null=True)
    source = peewee.CharField(default=None, null=True)

    # Прогресс.
    step = peewee.TextField(default=None, null=True)
    status = peewee.TextField(choices=StatusChoices.choices, default=StatusChoices.IN_PROGRESS)
    error_details = peewee.TextField(default=None, null=True)
    is_archived = peewee.BooleanField(default=False)
    request_log = peewee.ForeignKeyField(RequestLog, default=None, null=True)

    # Анализ и настройки выполнения задачи.
    transcript_id = peewee.TextField(default=None, null=True)
    analyze_id = peewee.TextField(default=None, null=True)
    analyze_data = peewee.TextField(default=None, null=True)
    analyze_input_tokens = peewee.IntegerField(default=None, null=True)
    analyze_output_tokens = peewee.IntegerField(default=None, null=True)
    assembly_duration = peewee.IntegerField(default=None, null=True,
                                            verbose_name='Продолжительность звонка (себестоимость)')
    initial_duration = peewee.IntegerField(default=None, null=True,
                                           verbose_name='Продолжительность звонка из CRM/телефонии')
    duration_sec = peewee.IntegerField(default=None, null=True, verbose_name='Фактическая продолжительность аудиофайла')
    file_url = peewee.TextField(default=None, null=True)
    data = peewee.TextField(default=json.dumps({}))

    def get_call_report(self) -> dict:
        """
        Формирует call_report на основе ответов на вопросы, сохраненных в базе данных.
        """
        if self.status != self.StatusChoices.DONE:
            return {}

        mode_questions = (
            ModeQuestion
            .select(
                ModeQuestion.short_name,
                ModeAnswer.answer_text,
            )
            .join(
                ModeAnswer,
                join_type=peewee.JOIN.LEFT_OUTER,
                on=(
                        (ModeAnswer.question == ModeQuestion.id) &
                        (ModeAnswer.task == self)
                )
            )
            .where(
                ModeQuestion.is_active == True,
                ModeQuestion.calc_type == ModeQuestionCalcType.AI,
                ModeQuestion.report == self.report,
            )
            .order_by(ModeQuestion.column_index.asc())
        )
        call_report = {}
        for mq in mode_questions:
            mode_answer = getattr(mq, 'modeanswer', None)
            answer_text = mode_answer.answer_text if mode_answer else 'Ответ не найден'
            call_report[mq.short_name] = answer_text

        return call_report

    def get_status_data(self) -> dict:
        data = self.get_data()

        call_report = self.get_call_report()
        result = {
            'account_id': data.get('account_id'),
            'telegram_id': data.get('telegram_id'),
            'task_id': data.get('task_id'),
            'call_id': data.get('call_id'),
            'report_status': data.get('report_status'),
            'status_message': data.get('status_message'),
            'call_report': call_report,
            'transcript': data.get('transcript'),
            'transcript_id': self.transcript_id,
        }

        task_settings = data.get('settings', {})
        task_result = data.get('result', {})

        if task_settings.get('advance_transcript'):
            result['advance_transcript_data'] = task_result.get('advance_transcript_data')

        return result

    def get_sorted_analyze_data(self):
        """
        Возвращает кортеж, отсортированный по индексу колонки в таблице звонков,
        содержащий название колонки и ответ от нейронной сети.
        Используется для выгрузки в Гугл Таблицу.
        """
        mode_questions = self.report.get_ai_columns()
        analyze_dict = json.loads(self.analyze_data)
        analyze_dict = {int(k): v for k, v in analyze_dict.items()}

        result = []
        for mq in mode_questions:
            if mq.id not in analyze_dict:
                continue

            answer_text = analyze_dict[mq.id]

            # Нормализация ответа для Гугл-Таблицы.
            if mq.answer_type == ModeQuestionType.PERCENT:
                answer_text = str(answer_text).strip()

                # Если в тексте ответа нет знака процента, то:
                # 1) для числовых ответов – добавляем % в конце ответа;
                # 2) для всех остальных – ничего не делаем (например, когда ответ "-").
                if '%' not in answer_text:
                    try:
                        answer_number = int(answer_text)
                    except ValueError:
                        try:
                            answer_number = float(answer_text.replace(',', '.'))
                        except ValueError:
                            answer_number = None

                    if answer_number is not None:
                        answer_text = f'{answer_number}%'

            result.append((mq.short_name, answer_text))

        return result


class ModeQuestionType(str, Enum):
    """
    Типы данных ответов, полученных от нейронки.

    Тип данных определяет то, как ответ будет обрабатываться в интерфейсе:
    1. Варианты операций в фильтрах по колонке.
    2. Варианты операций при построении графика по значению колонки.

    Например,
      фильтр по числовому значению можно применить только к колонкам
      с типом "число" или "процент", но не "дата", "строка" и т.д.
    """
    STRING = 'string'
    INTEGER = 'integer'
    PERCENT = 'percent'
    DATE = 'date'
    MULTIPLE_CHOICE = 'multiple_choice'
    LIST_OF_VALUES = 'list_of_values'


class ModeQuestionCalcType(str, Enum):
    """
    Типы колонок таблицы звонков.
    """

    # Ответ от нейронной сети.
    AI = 'ai'
    # Значение из внешней системы (CRM, телефония).
    CRM = 'crm'
    # Заданные программно вычисляемые значения.
    CUSTOM = 'custom'


class DefaultQuestions:
    """
    Кастомные колонки, создаваемые для каждого отчета по умолчанию.
    """

    @staticmethod
    def get_refresh_time_value(task: Optional['Task'] = None) -> str:
        return get_refresh_time()

    @staticmethod
    def get_duration_in_sec_value(task) -> Optional[int]:
        return task.assembly_duration

    question_functions = {
        'refresh_time': {
            'title': 'Дата добавления звонка',
            'func': get_refresh_time_value,
            'answer_type': ModeQuestionType.DATE,
        },
        'duration_in_sec': {
            'title': 'Длительность звонка',
            'func': get_duration_in_sec_value,
            'answer_type': ModeQuestionType.INTEGER,
        },
    }

    @classmethod
    def get_func(cls, title: str):
        for q in cls.question_functions.values():
            if q['title'] == title:
                return q['func']
        raise ValueError(f'Неизвестная вычисляемая колонка {title}.')


class ModeQuestion(BaseModel):
    """
    Колонка в таблице звонков.
    """
    created = peewee.DateTimeField(default=datetime.now)
    is_active = peewee.BooleanField()
    report = peewee.ForeignKeyField(Report)
    mode = peewee.ForeignKeyField(Mode, backref='questions', default=None, null=True)

    short_name = peewee.TextField(verbose_name='Название столбца')
    calc_type = peewee.CharField(default=ModeQuestionCalcType.AI.value,
                                 choices=[(x.value, x.value) for x in ModeQuestionCalcType],
                                 verbose_name='Тип вычисления')

    # Настройки отображения.
    column_index = peewee.IntegerField(verbose_name='Порядковый номер столбца', help_text='1-indexed')
    data = peewee.TextField(
        default='{\"frontend\":{\"css\":{\"width\":220,\"fixed\":false,\"filled\":false,\"inversion\":false}}}')

    # Параметры вопроса к AI (для ModeQuestionCalcType.AI).
    context = peewee.TextField(null=True, verbose_name='Контекст вопроса')
    question_text = peewee.TextField(verbose_name='Текст вопроса')
    answer_type = peewee.CharField(default=ModeQuestionType.STRING.value,
                                   choices=[(x.value, x.value) for x in ModeQuestionType],
                                   verbose_name='Тип данных ответа')
    answer_format = peewee.TextField(null=True, verbose_name='Формат ответа')
    answer_options = peewee.TextField(null=True, verbose_name='Варианты ответов')
    variant_colors = peewee.TextField(null=True, verbose_name='Цвета для answer_options')

    # Настройки CRM (для ModeQuestionCalcType.CRM).
    # Используются, когда нужно выгружать из CRM значение конкретного поля конкретной сущности.
    crm_entity_type = peewee.CharField(null=True)
    crm_id = peewee.CharField(null=True, help_text='Всегда заполняется для CRM-колонок')


class ModeTemplate(BaseModel):
    """
    Шаблон отчета.
    """
    created = peewee.DateTimeField(default=datetime.now)
    name = peewee.TextField()
    final_model = peewee.CharField()
    context = peewee.TextField(null=True, verbose_name='Общий контекст')


class ModeTemplateQuestion(BaseModel):
    """
    Вопросы шаблона отчета.
    """
    mode_template = peewee.ForeignKeyField(ModeTemplate)
    question = peewee.ForeignKeyField(ModeQuestion)


class ModeAnswer(BaseModel):
    """
    Ответ нейронной сети на вопрос.
    В рамках одного промпта может быть получено несколько ответов за запрос.
    """
    task = peewee.ForeignKeyField(Task)
    question = peewee.ForeignKeyField(ModeQuestion)
    answer_text = peewee.TextField(null=True)


class UserMode(BaseModel):
    user = peewee.ForeignKeyField(User, backref='modes', default=None, null=True)
    mode = peewee.ForeignKeyField(Mode, backref='users', default=None, null=True)


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


class VPBXCall(BaseModel):
    """
    Звонок Телефонии.
    Используется для проверки того, обрабатывали ли уже звонок.
    """
    timestamp = peewee.DateTimeField(default=datetime.now)
    integration = peewee.ForeignKeyField(Integration)
    call_id = peewee.CharField(max_length=255, verbose_name='ID звонка в Телефонии')
    call_created = peewee.DateTimeField(default=None, null=True, verbose_name='Время звонка')


class GSpreadTask(BaseModel):
    """
    Задача выгрузки строки с результатом анализа звонка в Google Sheets.
    Создается после обработки звонка.

    Данные для доступа к Таблице находятся в поле `mode`.
    Содержимое ячеек для записи – в поле `values_to_upload`.
    """
    created = peewee.DateTimeField(default=datetime.now, verbose_name='Дата создания')
    task = peewee.ForeignKeyField(Task, null=True, verbose_name='Задача')
    mode = peewee.ForeignKeyField(Mode, null=True, verbose_name='Режим')
    values_to_upload = peewee.TextField(verbose_name='Значения ячеек для выгрузки')

    retry_count = peewee.IntegerField(default=0, verbose_name='Количество попыток')
    last_attempt = peewee.DateTimeField(default=None, null=True, verbose_name='Время последней попытки')
    uploaded = peewee.DateTimeField(default=None, null=True, verbose_name='Дата успешной выгрузки')


class TableViewSettings(BaseModel):
    """
    Вид просмотра таблицы звонков.
    """

    class Meta:
        indexes = (
            (('report', 'user', 'name'), True),
        )

    created = peewee.DateTimeField(default=datetime.now)
    report = peewee.ForeignKeyField(Report)
    user = peewee.ForeignKeyField(User)
    name = peewee.CharField()

    def get_company_id(self) -> int:
        return self.report.integration.company.id


class ColumnDisplay(BaseModel):
    """
    Отображаемая колонка в виде просмотра таблицы звонков.
    """

    class Meta:
        indexes = (
            (('table_settings', 'mode_question'), True),
        )

    table_settings = peewee.ForeignKeyField(TableViewSettings)
    mode_question = peewee.ForeignKeyField(ModeQuestion)
    is_on = peewee.BooleanField()

    def get_company_id(self) -> int:
        return self.table_settings.get_company_id()


class TableActiveFilter(BaseModel):
    """
    Активный фильтр вида отображения таблицы.
    """
    table_settings = peewee.ForeignKeyField(TableViewSettings)
    mode_question = peewee.ForeignKeyField(ModeQuestion)
    operation = peewee.CharField()
    value = peewee.CharField()

    def clean(self):
        if self.table_settings.report != self.mode_question.report:
            raise ValueError('Нет такого вопроса в отчете')

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ColumnFilter:
    # Операции для всех типов данных колонок.
    FILTER_OPERATIONS = {
        ModeQuestionType.STRING: [
            {'operation': 'contains', 'display_name': 'Содержит'},
            {'operation': 'not_contains', 'display_name': 'Не содержит'},
            {'operation': 'starts_with', 'display_name': 'Начинается с'},
        ],
        ModeQuestionType.INTEGER: [
            {'operation': 'greater_or_equal', 'display_name': 'Больше или равно'},
            {'operation': 'less_or_equal', 'display_name': 'Меньше или равно'},
            {'operation': 'equal', 'display_name': 'Равно'},
        ],
        ModeQuestionType.DATE: [
            {'operation': 'greater_than', 'display_name': 'Дата от'},
            {'operation': 'less_than', 'display_name': 'Дата до'},
            {'operation': 'range', 'display_name': 'Дата от-до'},
            {'operation': 'exact_date', 'display_name': 'Конкретная дата'},
            {'operation': 'last_x_days', 'display_name': 'Последние X дней'},
        ],
        ModeQuestionType.MULTIPLE_CHOICE: [
            {'operation': 'contains_one_of', 'display_name': 'Содержит одно из'},
            {'operation': 'not_contains_any_of', 'display_name': 'Не содержит ни одно из'},
        ],
    }
    # Операции для процента те же, что и для числа.
    FILTER_OPERATIONS[ModeQuestionType.PERCENT] = deepcopy(FILTER_OPERATIONS[ModeQuestionType.INTEGER])
    # Операции для списка строк те же, что и для строки.
    FILTER_OPERATIONS[ModeQuestionType.LIST_OF_VALUES] = deepcopy(FILTER_OPERATIONS[ModeQuestionType.STRING])

    @staticmethod
    def build(
            field: peewee.Field,
            answer_type: str,
            operation: str,
            value: str,
    ):
        """
        Используется для фильтрации
        по полю field
        операцией operation
        со значением value.
        """

        operation = operation.lower()

        if answer_type in {ModeQuestionType.STRING,
                           ModeQuestionType.LIST_OF_VALUES}:
            # Регистронезависимый поиск.
            if operation == 'contains':
                return field.contains(value)
            elif operation == 'not_contains':
                return ~field.contains(value)
            elif operation == 'starts_with':
                return field.startswith(value)

        elif answer_type in {ModeQuestionType.INTEGER,
                             ModeQuestionType.PERCENT}:
            if operation == 'greater_or_equal':
                return field >= value
            elif operation == 'less_or_equal':
                return field <= value
            elif operation == 'equal':
                return field == value

        elif answer_type == ModeQuestionType.DATE:
            date_format = '%d.%m.%Y'
            postgresql_date_format = 'DD.MM.YYYY'

            if operation in {'greater_than', 'less_than', 'exact_date'}:
                date_value = datetime.strptime(value, date_format).date()
                if operation == 'greater_than':
                    return peewee.fn.TO_DATE(field, postgresql_date_format) >= date_value
                elif operation == 'less_than':
                    return peewee.fn.TO_DATE(field, postgresql_date_format) <= date_value
                elif operation == 'exact_date':
                    return peewee.fn.TO_DATE(field, postgresql_date_format) == value

            elif operation == 'range':
                from_value, to_value = value.split('-')
                from_date = datetime.strptime(from_value.strip(), date_format).date()
                to_date = datetime.strptime(to_value.strip(), date_format).date()
                return ((peewee.fn.TO_DATE(field, postgresql_date_format) >= from_date)
                        & (peewee.fn.TO_DATE(field, postgresql_date_format) <= to_date))

            elif operation == 'last_x_days':
                cutoff = datetime.now().date() - timedelta(days=int(value))
                return peewee.fn.TO_DATE(field, postgresql_date_format) > cutoff

        elif answer_type == ModeQuestionType.MULTIPLE_CHOICE:
            try:
                values_list = json.loads(value)
            except JSONDecodeError:
                values_list = [value]

            if operation == 'contains_one_of':
                return reduce(or_, [(field == v) for v in values_list])
            elif operation == 'not_contains_any_of':
                return reduce(and_, [(field != v) for v in values_list])

        logger.warning(f'Неподдерживаемый фильтр: {field=} {answer_type=} {operation=}')
        raise ValueError(f'Неподдерживаемый фильтр: {answer_type}.{operation}')


class Chart(BaseModel):
    """
    График отчета.
    """

    class Meta:
        indexes = (
            (('report', 'name'), True),
        )

    created = peewee.DateTimeField(default=datetime.now)
    report = peewee.ForeignKeyField(Report)
    name = peewee.CharField()
    order = peewee.IntegerField()

    def get_company_id(self) -> int:
        return self.report.integration.company.id


class ChartMetricType(str, Enum):
    INTEGER = 'integer'
    PERCENT = 'percent'
    MULTIPLE_CHOICE = 'multiple_choice'


MetricsOptions = {
    ChartMetricType.INTEGER: [
        {'operation': 'average', 'display_name': 'Среднее'},
        {'operation': 'max', 'display_name': 'Макс'},
        {'operation': 'min', 'display_name': 'Мин'},
        {'operation': 'sum', 'display_name': 'Сумма'},
        {'operation': 'count', 'display_name': 'Кол-во элементов'},
    ],
    ChartMetricType.PERCENT: [
        {'operation': 'average', 'display_name': 'Среднее'},
        {'operation': 'max', 'display_name': 'Макс'},
        {'operation': 'min', 'display_name': 'Мин'},
        {'operation': 'count', 'display_name': 'Кол-во элементов'},
    ],
    ChartMetricType.MULTIPLE_CHOICE: [
        {'operation': 'count', 'display_name': 'Кол-во элементов'},
        {'operation': 'percentage_of_total', 'display_name': '% от общего числа'},
    ],
}


class ChartParameter(BaseModel):
    class Meta:
        indexes = (
            (('chart', 'mode_question'), True),
        )

    chart = peewee.ForeignKeyField(Chart)
    mode_question = peewee.ForeignKeyField(ModeQuestion)

    color = peewee.CharField()
    data_type = peewee.CharField(choices=[(x.value, x.value) for x in ChartMetricType])
    metric_operation = peewee.CharField()
    metric_condition = peewee.CharField(default=None, null=True)  # Используется для множественного выбора.
    is_hidden = peewee.BooleanField()

    def clean(self):
        if self.mode_question.report.id != self.chart.report.id:
            raise ValueError('Колонка не принадлежит отчету графика')

        if self.data_type not in MetricsOptions:
            raise ValueError('Неизвестный тип метрики')

        possible_operations = [x['operation'] for x in MetricsOptions[self.data_type]]
        if self.metric_operation not in possible_operations:
            raise ValueError(f'Неизвестная операция "{self.metric_operation}" для типа данных "{self.data_type}"')

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ChartFilter(BaseModel):
    """
    Фильтр графика.
    """
    chart = peewee.ForeignKeyField(Chart)
    mode_question = peewee.ForeignKeyField(ModeQuestion)
    operation = peewee.CharField()
    value = peewee.CharField()

    def clean(self):
        if self.chart.report != self.mode_question.report:
            raise ValueError('Нет такого вопроса в отчете')

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


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
    MANGO = 'mango'
    ZOOM = 'zoom'
    TELEGRAM = 'telegram'


# Все модели, необходимые для работы приложения.
# Общий список может понадобиться, например, в тестах.
ALL_MODELS = [
    Company,
    User,
    Integration,
    Deal,
    Report,
    ActiveTelegramReport,
    RequestLog,
    Task,
    ModeQuestion,
    ModeAnswer,
    IntegratorCompany,
    Payment,
    ModeTemplate,
    Mode,
    UserMode,
    CallDownload,
    CallDownloadAMO,
    Transaction,
    VPBXCall,
    GSpreadTask,
    TableViewSettings,
    ColumnDisplay,
    TableActiveFilter,
    Chart,
    ChartParameter,
    ChartFilter,
]


def create_db_tables_if_not_exists() -> bool:
    logger.info(f"Проверяем и при необходимости создаем таблицы в БД.")
    with main_db:
        main_db.create_tables(ALL_MODELS)
    return True
