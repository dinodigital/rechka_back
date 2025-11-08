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

    # Компании.
    sys_admin_company = Company.create(name='Компания системного администратора')
    common_company = Company.create(name='Общая компания')
    admin_integrator_company = Company.create(name='Компания админа-интегратора')
    integrator_company = Company.create(name='Компания интегратора')

    # Пользователи:
    # 1. Системный админ. В своей компании является обычным пользователем.
    sys_admin = User.create(
        hashed_password=hashed_password,
        is_admin=True,
        company=sys_admin_company,
        company_role=Company.Roles.USER,
    )

    # 2. Админ своей компании + интегратор в компании admin_integrator_company.
    company_admin = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=common_company,
        company_role=Company.Roles.ADMIN,
    )
    IntegratorCompany.create(integrator=company_admin, company=admin_integrator_company)

    # 3. Обычные пользователи компаний: common_company, admin_integrator_company, integrator_company.
    user1 = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=common_company,
        company_role=Company.Roles.USER,
    )
    user2 = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=admin_integrator_company,
        company_role=Company.Roles.USER,
    )
    user3 = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=integrator_company,
        company_role=Company.Roles.USER,
    )

    # 4. Интегратор компании integrator_company. Не является админом своей компании.
    integrator = User.create(
        hashed_password=hashed_password,
        is_admin=False,
        company=common_company,
        company_role=Company.Roles.USER,
    )
    IntegratorCompany.create(integrator=integrator, company=integrator_company)

    yield {
        'user_password': user_password,
        'sys_admin': sys_admin,
        'company_admin': company_admin,
        'user1': user1,
        'user2': user2,
        'user3': user3,
        'integrator': integrator,
        'common_company': common_company,
        'admin_integrator_company': admin_integrator_company,
        'integrator_company': integrator_company,
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
    Не является интегратором ни в одной из компаний.
    Не является администратором своей компании.
    """
    client = TestClient(server)

    user_password = setup_db['user_password']
    sys_admin = setup_db['sys_admin']
    company_admin = setup_db['company_admin']
    integrator = setup_db['integrator']
    user1 = setup_db['user1']
    user2 = setup_db['user2']
    user3 = setup_db['user3']

    common_company = setup_db['common_company']

    # 1. Запрашивает пользователей всех компаний.
    # Видит всех пользователей всех компаний.
    headers = get_access_headers(client, sys_admin.id, user_password)
    response = client.get('/v2/lk/users/', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {sys_admin.id,
                        company_admin.id,
                        user1.id,
                        user2.id,
                        user3.id,
                        integrator.id}

    # 2. Запрашивает пользователей компании common_company.
    # Видит всех пользователей указанной компании.
    response = client.get(f'/v2/lk/users/?company_id={common_company.id}', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {company_admin.id,
                        user1.id,
                        integrator.id}

    # 3. Запрашивает пользователей своей компании, не являясь в ней администратором.
    # Видит пользователей запрошенной компании, так как является системным администратором.
    response = client.get(f'/v2/lk/users/?company_id={sys_admin.company.id}', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {sys_admin.id}


def test_company_admin(setup_db):
    """
    Администратор своей компании.
    Не является системным администратором.
    Является интегратором в компании admin_integrator_company.
    """
    client = TestClient(server)

    user_password = setup_db['user_password']
    company_admin = setup_db['company_admin']
    integrator = setup_db['integrator']
    user1 = setup_db['user1']
    user2 = setup_db['user2']

    admin_integrator_company = setup_db['admin_integrator_company']
    integrator_company = setup_db['integrator_company']

    # 1. Запрашивает всех пользователей системы.
    # Получает пользователей своей компании + пользователей компании, где он интегратор.
    headers = get_access_headers(client, company_admin.id, user_password)
    response = client.get('/v2/lk/users/', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {company_admin.id,
                        user1.id,
                        integrator.id,
                        user2.id}

    # 2. Запрашивает пользователей своей компании.
    # Видит всех пользователей своей компании.
    response = client.get(f'/v2/lk/users/?company_id={company_admin.company.id}', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {company_admin.id,
                        user1.id,
                        integrator.id}

    # 3. Запрашивает пользователей чужой компании, где он интегратор.
    # Видит пользователей запрошенной компании.
    response = client.get(f'/v2/lk/users/?company_id={admin_integrator_company.id}', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {user2.id}

    # 4. Запрашивает пользователей чужой компании, где он не интегратор.
    # Не видит ни одного пользователя.
    response = client.get(f'/v2/lk/users/?company_id={integrator_company.id}', headers=headers)
    assert response.status_code == 404


def test_integrator(setup_db):
    """
    Интегратор в чужой компании.
    Не является системным администратором.
    Не является администратором в своей компании.
    """
    client = TestClient(server)

    user_password = setup_db['user_password']
    integrator = setup_db['integrator']
    user3 = setup_db['user3']

    common_company = setup_db['common_company']
    integrator_company = setup_db['integrator_company']

    # 1. Запрашивает всех пользователей системы.
    # Видит пользователей компании, где он интегратор. Не видит пользователей своей компании, так как не админ.
    headers = get_access_headers(client, integrator.id, user_password)
    response = client.get('/v2/lk/users/', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {user3.id}

    # 2. Запрашивает пользователей чужой компании, где он интегратор.
    # Видит пользователей указанной компании.
    response = client.get(f'/v2/lk/users/?company_id={integrator_company.id}', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == {user3.id}

    # 3. Запрашивает пользователей компании, где он не интегратор.
    # Не видит ни одного пользователя.
    response = client.get(f'/v2/lk/users/?company_id={common_company.id}', headers=headers)
    assert response.status_code == 404


def test_user(setup_db):
    """
    Пользователь компании.
    Не является системным администратором.
    Не является администратором своей компании.
    Не является интегратором ни в одной из компаний.
    """
    client = TestClient(server)

    user_password = setup_db['user_password']
    user1 = setup_db['user1']
    common_company = setup_db['common_company']

    # 1. Запрашивает всех пользователей системы.
    # Не видит ни одного пользователя.
    headers = get_access_headers(client, user1.id, user_password)
    response = client.get('/v2/lk/users/', headers=headers)
    user_ids = {u['id'] for u in response.json()}
    assert user_ids == set()

    # 2. Запрашивает пользователей чужой компании.
    # Не видит ни одного пользователя.
    response = client.get(f'/v2/lk/users/?company_id={common_company.id}', headers=headers)
    assert response.status_code == 404

    # 3. Запрашивает пользователей своей компании.
    # Не видит ни одного пользователя.
    response = client.get(f'/v2/lk/users/?company_id={user1.company.id}', headers=headers)
    assert response.status_code == 404
