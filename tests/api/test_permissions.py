import pytest
from fastapi.testclient import TestClient

from config import config as cfg
from data.models import IntegratorCompany
from data.models import ReconnectPostgresqlDatabase, User, Company
from routers.auth import get_password_hash
from server import server


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
        IntegratorCompany,
    ]
    for model in models:
        model._meta.database = test_db

    test_db.bind(models, bind_refs=True, bind_backrefs=True)
    test_db.connect()
    test_db.create_tables(models)

    # Создаем тестовые сущности.
    user_password = 'password'
    hashed_password = get_password_hash(user_password)

    admins_company = Company.create(name='sys admin and admin company')
    user_company = Company.create(name='user company')

    # Системный админ.
    sys_admin = User.create(
        hashed_password=hashed_password,
        is_admin=True,
        company=admins_company,
        company_role=Company.Roles.USER,
    )
    # Админ компании.
    company_admin = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=admins_company,
        company_role=Company.Roles.ADMIN,
    )
    # Обычный пользователь.
    user = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=user_company,
        company_role=Company.Roles.USER,
    )

    yield {
        'user_password': user_password,
        'sys_admin': sys_admin,
        'company_admin': company_admin,
        'user': user,
    }

    test_db.drop_tables(models)
    test_db.close()


def get_access_headers(
        client: TestClient,
        user_id: int,
        password: str,
) -> dict:
    """
    Возвращает заголовки запроса авторизованного пользователя.
    """
    response = client.post('/v2/lk/token/', data={'username': user_id, 'password': password})
    token = response.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    return headers


def test_sys_admin(setup_db):
    """
    Системный администратор.
    Не является администратором своей компании.
    """
    client = TestClient(server)

    sys_admin = setup_db['sys_admin']
    user_password = setup_db['user_password']

    headers = get_access_headers(client, sys_admin.id, user_password)
    
    ok_urls = [
        '/v2/lk/check/sys_admin/',
        '/v2/lk/check/admin/',
        '/v2/lk/check/user/',
        '/v2/lk/check/user_or_admin/',
    ]
    for url in ok_urls:
        response = client.get(url, headers=headers)
        assert response.json()['id'] == sys_admin.id


def test_admin(setup_db):
    """
    Администратор своей компании.
    Не является системным администратором.
    """
    client = TestClient(server)

    company_admin = setup_db['company_admin']
    user_password = setup_db['user_password']

    headers = get_access_headers(client, company_admin.id, user_password)

    ok_urls = [
        '/v2/lk/check/admin/',
        '/v2/lk/check/user_or_admin/'
    ]
    for url in ok_urls:
        response = client.get(url, headers=headers)
        assert response.json()['id'] == company_admin.id

    urls_403 = [
        '/v2/lk/check/sys_admin/',
        '/v2/lk/check/user/',
    ]
    for url in urls_403:
        response = client.get(url, headers=headers)
        assert response.status_code == 403


def test_user(setup_db):
    """
    Пользователь своей компании.
    Не является администратором своей компании.
    Не является системным администратором.
    """
    client = TestClient(server)

    user = setup_db['user']
    user_password = setup_db['user_password']

    headers = get_access_headers(client, user.id, user_password)

    ok_urls = [
        '/v2/lk/check/user/',
        '/v2/lk/check/user_or_admin/'
    ]
    for url in ok_urls:
        response = client.get(url, headers=headers)
        assert response.json()['id'] == user.id

    urls_403 = [
        '/v2/lk/check/sys_admin/',
        '/v2/lk/check/admin/',
    ]
    for url in urls_403:
        response = client.get(url, headers=headers)
        assert response.status_code == 403
