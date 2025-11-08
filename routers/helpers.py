from typing import Union, List, Optional

import peewee
from fastapi import Request
from loguru import logger
from pydantic import BaseModel

from data.models import User
from data.server_models import CustomCallRequest, CustomTaskRequest, AuthRequest


def log_access_denied(
        data_request: Union[AuthRequest, CustomCallRequest, CustomTaskRequest],
        request: Request,
) -> None:
    request_data_json = data_request.model_dump_json(exclude={'client_secret'})
    logger.error(f'В доступе отказано. Код ответа: 403. '
                 f'[{request.method.upper()}] {request.url.path} {request_data_json=}')
    return None


def update_endpoint_object(
        obj: peewee.Model,
        data: BaseModel,
        update_for_none: bool,
        commit: bool = True,
        ignore_fields: List[str] = None,
):
    """
    Обновляет поля obj значениями data.
    Возвращает измененный объект.

    obj: объект модели peewee.
    data: значения полей для обновления, переданные пользователем.
    update_for_none: обновлять поле, если в data None. True для PUT, False для PATCH.
    commit: сохранить изменения в БД.
    ignore_fields: позволяет указать поля, которые не нужно обновлять.
    """
    if ignore_fields is None:
        ignore_fields = []

    schema_fields = data.__class__.model_fields
    for field_name in schema_fields:
        if field_name in ignore_fields:
            continue
        new_value = getattr(data, field_name)
        if update_for_none or new_value is not None:
            setattr(obj, field_name, new_value)

    if commit and obj.is_dirty():
        obj.save()

    return obj


def check_user_role(
        user_id: int,
        roles: List[str],
) -> Optional[User]:
    """
    Проверяет у пользователя с id=user_id наличие хотя бы одной из ролей, перечисленных в roles.

    Доступ разрешен:
        1. Системный администратор (user.is_admin is True):
           - Имеет доступ всегда и ко всему.
        2. Пользователь, у которого значение company_role содержится в roles.

    В доступе отказано:
        1. Пользователь с user_id не найден в БД.
        2. Передан пустой список ролей (roles).
        3. У пользователя в БД нет установленного значения роли (.company_role).
        4. Пользователь не имеет хотя бы одну из ролей, перечисленных в roles.

    Результат:
        - объект пользователя (User), если доступ разрешен.
        - None, если в доступе отказано.
    """
    user = User.get_or_none(User.id == user_id)

    # Пользователь в БД не найден.
    if user is None:
        return None

    # Администратор системы имеет полный доступ.
    if user.is_admin:
        return user

    # Пустой список ролей – в доступе отказано.
    if not roles:
        return None

    # У пользователя нет роли в компании - в доступе отказано.
    if not user.company_role:
        return None

    if user.company_role in roles:
        return user

    return None
