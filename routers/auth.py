import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated, List, Union

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from loguru import logger
from starlette import status

from config import config as cfg
from config.config import ACCESS_TOKEN_EXPIRE_MINUTES
from data.models import User, Company
from modules.exceptions import TelegramDataIsOutdated, TelegramBadHashError
from routers.helpers import check_user_role
from schemas.user import UserInDB, TokenData, UserModel, Token, TelegramAuthSchema
from telegram_bot.handlers.on_cmd import get_or_register_telegram_user


route_prefix = '/v2/lk'
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f'{route_prefix}/token')

router = APIRouter()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def get_user(user_id: int) -> Optional[UserInDB]:
    user = User.get_or_none(User.id == user_id)
    if user:
        return UserInDB(
            id=user_id,
            created=user.created,
            tg_id=user.tg_id,
            hashed_password=user.hashed_password,
            full_name=user.full_name,
            email=user.email,
            company_id=user.company.id if user.company else None,
            company_role=user.company_role,
            is_admin=user.is_admin,
        )
    return None


def authenticate_user(user_id: int, password: str) -> Optional[UserInDB]:
    user = get_user(user_id)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
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
        token_data = TokenData(user_id=int(user_id))
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(token_data.user_id)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
        current_user: Annotated[UserModel, Depends(get_current_user)],
) -> UserModel:
    # После проверки авторизации пароль не нужен.
    del current_user.hashed_password
    return current_user


@router.post('/token')
async def login_for_access_token(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user_id = int(form_data.username)
    user = authenticate_user(user_id, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect username or password',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    access_token_expires = timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': str(user.id)}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type='bearer')


def check_current_user_role(
        roles: Union[str, List[str]],
):
    """
    Возвращает функцию,
        которую можно использовать как зависимость для проверки прав доступа пользователя по его роли.
    Такая функция:
        - возвращает успешно авторизовавшегося пользователя (объект User), если доступ разрешен;
        – вызывает исключение со статусом 403, если в доступе отказано.
    """
    if isinstance(roles, str):
        roles = [roles]

    def _check_current_user(
            current_user: Annotated[UserModel, Depends(get_current_active_user)],
    ) -> User:
        user = check_user_role(current_user.id, roles)
        if user is None:
            logger.warning(f'Пользователь ID={current_user.id} запросил доступ {roles=} и потерпел неудачу.')
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail='В доступе отказано.')
        return user

    return _check_current_user


@router.get('/check/sys_admin', response_model=UserModel)
def check_sys_admin(
        current_user: Annotated[User, Depends(check_current_user_role([]))],
):
    return current_user


@router.get('/check/admin', response_model=UserModel)
def check_admin(
        current_user: Annotated[User, Depends(check_current_user_role(Company.Roles.ADMIN))],
):
    return current_user


@router.get('/check/user', response_model=UserModel)
def check_user(
        current_user: Annotated[User, Depends(check_current_user_role(Company.Roles.USER))],
):
    return current_user


@router.get('/check/user_or_admin', response_model=UserModel)
def check_user_or_admin(
        current_user: Annotated[User, Depends(check_current_user_role([Company.Roles.USER, Company.Roles.ADMIN]))],
):
    return current_user


def authenticate_telegram_user(
        form_data: TelegramAuthSchema
) -> dict:

    data = form_data.model_dump()

    # Проверяем, не устарела ли сессия. Время жизни Telegram-сессии такое же, что и у oauth2-сессии.
    auth_date = data.get('auth_date')
    if int(time.time()) - int(auth_date) > (ACCESS_TOKEN_EXPIRE_MINUTES * 60):
        raise TelegramDataIsOutdated('Сессия Telegram устарела')

    # Вычисляем хэш для сравнения согласно документации Telegram.
    received_hash = data.pop('hash', None)
    data_sorted = sorted(data.items(), key=lambda v: v[0])
    data_check_string = '\n'.join(f'{k}={v}' for k, v in data_sorted)

    secret_key = hashlib.sha256(cfg.BOT_TOKEN.encode()).digest()
    generated_hash = hmac.new(secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()

    if generated_hash != received_hash:
        raise TelegramBadHashError('Полученные данные некорректны')

    return data


@router.post('/tg_token')
async def telegram_login_for_access_token(
        form_data: TelegramAuthSchema = Depends(TelegramAuthSchema),
) -> Token:
    """
    Авторизация через Telegram Widget.
    Создает пользователя в БД, если авторизованный пользователь ранее не регистрировался через Telegram-бота.

    Документация к Telegram Login Widget:
        https://core.telegram.org/widgets/login
    """

    # Валидируем данные от Telegram API.
    try:
        validated_telegram_data = authenticate_telegram_user(form_data)
    except TelegramDataIsOutdated as ex:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ex.args[0])
    except TelegramBadHashError as ex:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=ex.args[0])

    # Полное имя пользователя в Telegram.
    full_name = validated_telegram_data['first_name']
    last_name = validated_telegram_data['last_name']
    if last_name:
        full_name = f'{full_name} {last_name}' if full_name else last_name

    # Создаем пользователя, если нужно.
    db_user, created = get_or_register_telegram_user(validated_telegram_data['id'],
                                                     username=validated_telegram_data['username'],
                                                     full_name=full_name)

    access_token_expires = timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': str(db_user.id)}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type='bearer')
