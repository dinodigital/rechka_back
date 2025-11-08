import pytest

from config import config as cfg
from data.models import ReconnectPostgresqlDatabase, User, Company, Transaction
from helpers.db_helpers import not_enough_company_balance


# Тестовая временная база данных.
test_db = ReconnectPostgresqlDatabase(
    cfg.PYTEST_TEMP_POSTGRES_DB,
    host=cfg.PYTEST_TEMP_POSTGRES_HOST,
    port=cfg.PYTEST_TEMP_POSTGRES_PORT,
    sslmode=cfg.PYTEST_TEMP_POSTGRES_SSL_MODE,
    user=cfg.PYTEST_TEMP_POSTGRES_USER,
    password=cfg.PYTEST_TEMP_POSTGRES_PASSWORD,
    target_session_attrs='read-write',
)


@pytest.fixture(scope='function')
def setup_db():

    # Привязываем модели к тестовой базе данных.
    models = [
        User,
        Company,
        Transaction,
    ]
    for model in models:
        model._meta.database = test_db

    test_db.bind(models, bind_refs=True, bind_backrefs=True)
    test_db.connect()
    test_db.create_tables(models)

    # Тестовые компании.
    company1 = Company.create(name='company 1')
    company2 = Company.create(name='company 2')

    yield {
        'company1': company1,
        'company2': company2,
        'minutes_delta': 10,
    }

    test_db.drop_tables(models)
    test_db.close()


def test_transfer_balance(setup_db):
    """
    Перевод баланса между двумя компаниями.
    """
    company1 = setup_db['company1']
    company2 = setup_db['company2']
    minutes_delta = setup_db['minutes_delta']

    # Балансы до изменения.
    company1_initial_balance = company1.seconds_balance
    company2_initial_balance = company2.seconds_balance

    Company.transfer_balance(company1, company2, minutes_delta)

    # Балансы после изменения.
    company1_result_balance = Company.get(id=company1.id).seconds_balance
    company2_result_balance = Company.get(id=company2.id).seconds_balance

    assert company1_result_balance == company1_initial_balance + (-minutes_delta * 60)
    assert company2_result_balance == company2_initial_balance + (minutes_delta * 60)

    # Для каждой стороны обмена в БД создается отдельная транзакция.
    transactions = Transaction.select()
    assert transactions.count() == 2


def test_plus_balance_with_transaction(setup_db):
    """
    Добавление баланса с созданием транзакции.
    """
    company1 = setup_db['company1']
    minutes_delta = setup_db['minutes_delta']

    company1_initial_balance = company1.seconds_balance
    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0

    transaction = company1.add_balance(minutes_delta * 60,
                                       payment_sum=10,
                                       payment_type=Transaction.PaymentType.ADMIN,
                                       description='test')

    company1_result_balance = Company.get(id=company1.id).seconds_balance
    assert company1_result_balance == company1_initial_balance + (minutes_delta * 60)

    # Проверяем, корректно ли заполнились поля транзакции.
    assert transaction.payment_type == Transaction.PaymentType.ADMIN
    assert transaction.payment_sum == minutes_delta
    assert transaction.description == 'test'
    assert transaction.company == company1

    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 1


def test_plus_balance_without_transaction(setup_db):
    """
    Добавление баланса без создания транзакции.
    """
    company1 = setup_db['company1']
    minutes_delta = setup_db['minutes_delta']

    company1_initial_balance = company1.seconds_balance
    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0

    transaction = company1.add_balance(minutes_delta * 60)

    company1_result_balance = Company.get(id=company1.id).seconds_balance
    assert company1_result_balance == company1_initial_balance + (minutes_delta * 60)

    assert transaction is None

    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0


def test_plus_balance_less_than_60(setup_db):
    # Минимальная величина для изменения баланса равна 60 секундам.

    company1 = setup_db['company1']

    for plus_seconds, result_delta in [
        (30, 60),
        (50, 60),
        (59, 60),
        (60, 60),
        (61, 61),
        (90, 90),
    ]:
        initial_balance = Company.get(id=company1.id).seconds_balance
        company1.add_balance(plus_seconds)
        result_balance = Company.get(id=company1.id).seconds_balance
        assert result_balance == initial_balance + result_delta


def test_minus_balance_with_transaction(setup_db):
    """
    Снятие баланса с созданием транзакции.
    """
    company1 = setup_db['company1']
    minutes_delta = setup_db['minutes_delta']

    company1_initial_balance = company1.seconds_balance
    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0

    transaction = company1.add_balance(-minutes_delta * 60,
                                       payment_sum=10,
                                       payment_type=Transaction.PaymentType.ADMIN,
                                       description='test')

    company1_result_balance = Company.get(id=company1.id).seconds_balance
    assert company1_result_balance == company1_initial_balance + (-minutes_delta * 60)

    # Проверяем, корректно ли заполнились поля транзакции.
    assert transaction.payment_type == Transaction.PaymentType.ADMIN
    assert transaction.payment_sum == minutes_delta
    assert transaction.description == 'test'
    assert transaction.company == company1

    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 1


def test_minus_balance_without_transaction(setup_db):
    """
    Снятие баланса без создания транзакции.
    """
    company1 = setup_db['company1']
    minutes_delta = setup_db['minutes_delta']

    company1_initial_balance = company1.seconds_balance
    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0

    transaction = company1.add_balance(-minutes_delta * 60)

    company1_result_balance = Company.get(id=company1.id).seconds_balance
    assert company1_result_balance == company1_initial_balance + (-minutes_delta * 60)

    assert transaction is None

    company1_transactions = Transaction.select().where(Transaction.company == company1)
    assert company1_transactions.count() == 0


def test_minus_balance_less_than_60(setup_db):
    # Минимальная величина для изменения баланса равна 60 секундам.

    company1 = setup_db['company1']
    company1.seconds_balance = 1000
    company1.save(only=['seconds_balance'])

    for plus_seconds, result_delta in [
        (30, 60),
        (50, 60),
        (59, 60),
        (60, 60),
        (61, 61),
        (90, 90),
    ]:
        initial_balance = Company.get(id=company1.id).seconds_balance
        company1.add_balance(-plus_seconds)
        result_balance = Company.get(id=company1.id).seconds_balance
        assert result_balance == initial_balance - result_delta


def test_balance_sufficient(setup_db):
    company1 = setup_db['company1']

    # Проверяем, достаточно ли баланса 10 для анализа 9, 10 и 11.
    company1.seconds_balance = 10
    company1.save(only=['seconds_balance'])

    result = not_enough_company_balance(company1, 9)
    assert result is False

    result = not_enough_company_balance(company1, 10)
    assert result is False

    result = not_enough_company_balance(company1, 11)
    assert result is True

    # Проверяем, достаточно ли баланса 11 для анализа 9, 10, 11 и 12.
    company1.seconds_balance = 11
    company1.save(only=['seconds_balance'])

    result = not_enough_company_balance(company1, 9)
    assert result is False

    result = not_enough_company_balance(company1, 10)
    assert result is False

    result = not_enough_company_balance(company1, 11)
    assert result is False

    result = not_enough_company_balance(company1, 12)
    assert result is True

