import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated, List, Dict

import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, Field, ConfigDict

from config import config as cfg
from data.models import User, Integration, IntegrationServiceName
from integrations.amo_crm.amo_api_core import AmoApi
from integrations.bitrix.bitrix_api import Bitrix24
from modules.exceptions import IntegrationConnectError, ObjectNotFoundError, IntegrationExistsError
from modules.json_processor.integration import IntegrationConstructor
from sipuni import SipuniFile


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: str | None = None


class UserModel(BaseModel):
    created: datetime
    user_id: str
    tg_id: int
    seconds_balance: int


class UserInDB(UserModel):
    hashed_password: str


pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

route_prefix = '/v2/lk'
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f'{route_prefix}/token')

router = APIRouter()


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user(user_id: str) -> Optional[UserInDB]:
    user = User.get_or_none(User.id == user_id)
    if user:
        return UserInDB(
            created=user.created,
            user_id=user_id,
            tg_id=user.tg_id,
            seconds_balance=user.seconds_balance,
            hashed_password=user.hashed_password,
        )
    return None


def authenticate_user(user_id: str, password: str) -> Optional[UserInDB]:
    user = get_user(user_id)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(to_encode, cfg.SECRET_KEY, algorithm=cfg.CRYPTO_ALGORITHM)
    return encoded_jwt


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.CRYPTO_ALGORITHM])
        user_id = payload.get('sub')
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=user_id)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(token_data.user_id)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
        current_user: Annotated[UserModel, Depends(get_current_user)],
):
    if current_user.hashed_password is None:
        raise HTTPException(status_code=400, detail='Inactive user')
    return current_user


@router.post('/token')
async def login_for_access_token(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect username or password',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    access_token_expires = timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': user.user_id}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type='bearer')


@router.get('/users/me/', response_model=UserModel)
async def read_users_me(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    return current_user


class UserPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tg_id: int


class IntegrationPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    service_name: IntegrationServiceName
    account_id: str
    user: UserPublicSchema
    data: str


@router.get('/integrations/{integration_id}', response_model=IntegrationPublicSchema)
async def get_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    """
    Получить интеграцию по переданному ID.
    """
    integration = Integration.get_or_none(Integration.id == integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail='Интеграция не найдена.')
    return integration


@router.get('/integrations', response_model=List[IntegrationPublicSchema])
async def get_integrations_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        tg_id: Optional[int] = Query(None),
        service_name: Optional[IntegrationServiceName] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    """
    Возвращает список интеграций с применением фильтров:
    - tg_id: Telegram ID пользователя интеграции;
    - service_name: тип системы;
    - limit: максимальное количество записей для вывода;
    - offset: начальная позиция выборки.
    """
    db_query = Integration.select()

    if tg_id is not None:
        user = User.get_or_none(User.tg_id == tg_id)
        if user is None:
            return []
        db_query = db_query.where(Integration.user == user)

    if service_name:
        db_query = db_query.where(Integration.service_name == service_name)

    integrations = db_query.limit(limit).offset(offset)
    return integrations


class IntegrationCreateSchema(BaseModel):
    """
    Схема для создания интеграции.
    """
    model_config = ConfigDict(from_attributes=True)

    service_name: IntegrationServiceName
    account_id: str
    telegram_id: int
    data: Dict


@router.post('/integrations', response_model=IntegrationPublicSchema)
async def create_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_data: IntegrationCreateSchema,
):
    constructor = IntegrationConstructor(integration_data.telegram_id,
                                         integration_data.account_id,
                                         integration_data.data,
                                         integration_data.service_name)
    try:
        integration = constructor.create()
    except ObjectNotFoundError as ex:
        raise HTTPException(status_code=404, detail=f'Не удалось создать интеграцию. {ex}')
    except (IntegrationConnectError, IntegrationExistsError) as ex:
        raise HTTPException(status_code=503, detail=f'Не удалось создать интеграцию. {ex}')

    return integration


class IntegrationUpdateSchema(BaseModel):
    """
    Схема для обновления интеграции.
    """
    model_config = ConfigDict(from_attributes=True)

    telegram_id: int
    account_id: str
    data: Dict


@router.put('/integrations/{integration_id}', response_model=IntegrationPublicSchema)
async def update_integration(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
        integration_data: IntegrationUpdateSchema,
):
    integration = Integration.get_or_none(Integration.id == integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail='Интеграция с таким ID не найдена.')

    constructor = IntegrationConstructor(integration_data.telegram_id,
                                         integration_data.account_id,
                                         integration_data.data,
                                         integration.service_name)
    try:
        updated_integration = constructor.update(integration)
    except ObjectNotFoundError as ex:
        raise HTTPException(status_code=404, detail=f'Не удалось создать интеграцию. {ex}')
    except IntegrationConnectError as ex:
        raise HTTPException(status_code=503, detail=f'Не удалось создать интеграцию. {ex}')

    return updated_integration


class CRMUserPublicScheme(BaseModel):
    """
    Пользователь CRM-системы (AmoCRM, Bitrix24, SipUni).
    """
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    name: str


@router.get('/integrations/{integration_id}/users', response_model=List[CRMUserPublicScheme])
async def get_users(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    integration = Integration.get_or_none(Integration.id == integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail='Интеграция с таким ID не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(status_code=400, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        response = amo_api.get_users()

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)

        users = await asyncio.to_thread(bx24.get_users)
        response = []
        for user in users:
            # Имя + Отчество + Фамилия. Пустые компоненты пропускаем.
            full_name = ' '.join(
                x for x in (
                    user.get('NAME'),
                    user.get('SECOND_NAME'),
                    user.get('LAST_NAME'))
                if x
            )
            response.append(CRMUserPublicScheme(id=user['ID'], name=full_name))

    elif integration.service_name == IntegrationServiceName.SIPUNI:
        token = json.loads(integration.data).get('access').get('application_token')
        client = SipuniFile(integration.account_id, token)

        csv_users = client.get_managers()
        response = []
        for line in csv_users.splitlines()[1:]:
            fields = line.split(';')
            user_id = int(fields[0])
            user_name = fields[1].strip('" ')
            response.append(CRMUserPublicScheme(id=user_id, name=user_name))

    else:
        raise HTTPException(status_code=400, detail='Неизвестный тип интеграции.')

    return response


class CRMFieldPublicSchema(BaseModel):
    """
    Поля CRM/телефонии. Системные + пользовательские.
    """
    id: Annotated[int, Field(examples=[1])]
    name: str
    value: Optional[str] = None
    options: Optional[List[dict]] = None


@router.get('/integrations/{integration_id}/fields/{entity_type}', response_model=List[CRMFieldPublicSchema])
async def get_integration_fields(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
        entity_type: str,
):
    """
    Возвращает все поля CRM/телефонии для указанного типа сущности.
    """
    integration = Integration.get_or_none(Integration.id == integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail='Интеграция с таким ID не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(status_code=400, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        try:
            fields = amo_api.get_custom_fields(entity_type)
        except TypeError:
            raise HTTPException(status_code=400, detail='Не удалось получить список полей. Проверьте интеграцию.')
        response = [
            CRMFieldPublicSchema(
                id=x['id'],
                name=x['name'],
                options=x['enums'],
            ) for x in fields
        ]

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)

        fields = await asyncio.to_thread(bx24.parse_bitrix_custom_fields)
        response = [
            CRMFieldPublicSchema(
                id=x['id'],
                name=x['name'],
                value=x['value'],
                options=x['options'],
            ) for x in fields
        ]

    else:
        raise HTTPException(status_code=400, detail='Неизвестный тип интеграции.')

    return response


class PipelinePublicScheme(BaseModel):
    """
    Воронки с этапами.
    """
    id: Annotated[int, Field(examples=[1])]
    name: str
    statuses: Optional[List[dict]] = None


@router.get('/integrations/{integration_id}/pipelines_and_statuses', response_model=List[PipelinePublicScheme])
async def get_integration_pipelines(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        integration_id: int,
):
    integration = Integration.get_or_none(Integration.id == integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail='Интеграция не найдена.')

    if integration.service_name == IntegrationServiceName.AMOCRM:
        try:
            amo_api = AmoApi(integration)
        except KeyError:
            raise HTTPException(status_code=400, detail='Не удалось подключиться к CRM. Проверьте интеграцию.')
        pipelines = amo_api.get_pipelines()
        response = [
            PipelinePublicScheme(
                id=x['id'],
                name=x['name'],
                statuses=x['statuses'],
            ) for x in pipelines
        ]

    elif integration.service_name == IntegrationServiceName.BITRIX24:
        webhook_url = integration.get_decrypted_access_field('webhook_url')
        bx24 = Bitrix24(webhook_url)
        pipelines = await asyncio.to_thread(bx24.get_funnels_with_stages)
        response = [
            PipelinePublicScheme(
                id=x['id'],
                name=x['name'],
                statuses=x['stages'],
            ) for x in pipelines
        ]

    else:
        raise HTTPException(status_code=400, detail='Неизвестный тип интеграции.')

    return response
