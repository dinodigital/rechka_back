from operator import or_
from typing import Optional, Annotated, List, Union

from fastapi import APIRouter, Depends, Query, HTTPException
from starlette.status import HTTP_404_NOT_FOUND, HTTP_400_BAD_REQUEST

from data.models import User, Company
from routers.auth import get_current_active_user, authenticate_user, get_password_hash
from routers.helpers import update_endpoint_object
from schemas.user import UserModel, UserMeUpdateSchema, PasswordUpdateSchema, UserCreateSchema, UserPartialUpdateSchema, \
    UserCompanyUpdateSchema, SysAdminPasswordUpdateSchema

router = APIRouter()


@router.get('/users/me/', response_model=UserModel)
async def read_users_me(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    return current_user


@router.put('/users/me/', response_model=UserModel)
async def update_users_me(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: UserMeUpdateSchema,
):
    user = User.get(id=current_user.id)
    user = update_endpoint_object(user, data, True)
    return user


def check_and_update_user_password(
        user_id: int,
        new_password: str,
        old_password: Union[str, None],
) -> UserModel:
    """
    Обновляет пароль пользователя с ID=user_id.

    Если передан текущий пароль old_password, то он проверяется на корректность.
    Иначе пароль обновляется без такой проверки.
    """

    if old_password is not None:
        # Проверяем текущий пароль.
        authenticated_user = authenticate_user(user_id, old_password)
        if authenticated_user is None:
            raise HTTPException(HTTP_400_BAD_REQUEST, detail='Неверный текущий пароль.')

    # Обновляем пароль.
    user = User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Пользователь не найден.')
    user.hashed_password = get_password_hash(new_password)
    user.save(only=['hashed_password'])

    return user


@router.put('/users/me/password', response_model=UserModel)
async def update_my_password(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: PasswordUpdateSchema,
):
    """
    Обновляет пароль авторизованного пользователя,
    если введен корректно текущий пароль.
    """
    user = check_and_update_user_password(current_user.id, data.new_password, data.old_password)
    return user


@router.get('/users/', response_model=List[UserModel])
async def get_users_list(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        company_id: Optional[int] = Query(None),
        user_or_tg_id: Optional[int] = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
):
    """
    Возвращает список пользователей:
    - админ системы -> все компании;
    - админ компании -> его компания + компании, где он интегратор;
    - интегратор -> компании, где он интегратор.

    Если company_id передан, доступ проверяется только к этой компании.
    Если передан user_or_tg_id, то происходит поиск по полям пользователя: User.id, User.tg_id.
    """
    db_user = User.get(id=current_user.id)
    db_query = User.select()

    # Получаем компании, к которым пользователь имеет доступ.
    companies = db_user.get_accessible_companies(company_id=company_id)
    if company_id is not None:
        if not companies.exists():
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail='Компания не найдена.')
    db_query = db_query.where(User.company.in_(companies))

    if user_or_tg_id is not None:
        db_query = db_query.where(or_(User.id == user_or_tg_id, User.tg_id == user_or_tg_id))

    users = db_query.limit(limit).offset(offset).order_by(User.id.asc())
    return users


@router.post('/users', response_model=UserModel)
async def create_user(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        data: UserCreateSchema,
):
    """
    Создает пользователя в компании с id=data.company_id.
    Доступно только администратору компании data.company_id и системному администратору.
    """
    if (
            not current_user.is_admin
            and
            not (current_user.company.id == data.company_id and current_user.company_role == Company.Roles.ADMIN)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    company = Company.get_or_none(id=data.company_id)
    if company is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    hashed_password = get_password_hash(data.password)
    new_user = User.create(
        hashed_password=hashed_password,
        company=company,
        company_role=data.company_role,
        full_name=data.full_name,
        email=data.email,
    )
    return new_user


@router.patch('/users/{user_id}', response_model=UserModel)
async def partial_update_user(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        user_id: int,
        data: UserPartialUpdateSchema,
):
    """
    Изменяет данные пользователя.
    Доступно только администратору компании пользователя с id=user_id и системному администратору.
    """
    user_to_update = User.get_or_none(id=user_id)

    if user_to_update is None or (
            not current_user.is_admin
            and
            not (user_to_update.company.id == current_user.company.id and current_user.company_role == Company.Roles.ADMIN)
    ):
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Пользователь не найден.')

    user = update_endpoint_object(user_to_update, data, False)
    return user


@router.patch('/users/{user_id}/company', response_model=UserModel)
async def update_user_company(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        user_id: int,
        data: UserCompanyUpdateSchema,
):
    # Обновлять компанию пользователя может только системный администратор.
    if not current_user.is_admin:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Пользователь не найден.')

    user = User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Пользователь не найден.')

    new_company = Company.get_or_none(id=data.company_id)
    if new_company is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Компания не найдена.')

    user.company = new_company
    user.save(only=['company'])

    return user


@router.put('/users/{user_id}/password', response_model=UserModel)
async def update_user_password(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        user_id: int,
        data: SysAdminPasswordUpdateSchema,
):
    """
    Обновляет пароль указанного пользователя.
    Доступно только системному администратору.
    """
    if not current_user.is_admin:
        raise HTTPException(HTTP_404_NOT_FOUND, detail='Пользователь не найден.')

    user = check_and_update_user_password(user_id, data.new_password, None)
    return user

