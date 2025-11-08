from datetime import datetime
from typing import Optional, Annotated

from pydantic import BaseModel, Field

from data.models import Company


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: int


class UserModel(BaseModel):
    id: Annotated[int, Field(examples=[1])]
    created: datetime
    tg_id: Optional[int] = None
    tg_username: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    company_id: Optional[int] = None
    company_role: Optional[Company.Roles] = None
    is_admin: bool


class UserInDB(UserModel):
    hashed_password: Optional[str] = None


class UserCreateSchema(BaseModel):
    password: str
    company_id: int
    company_role: str
    full_name: str
    email: str


class UserMeUpdateSchema(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None


class PasswordUpdateSchema(BaseModel):
    old_password: str
    new_password: str


class SysAdminPasswordUpdateSchema(BaseModel):
    new_password: str


class UserPartialUpdateSchema(BaseModel):
    company_role: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None


class UserCompanyUpdateSchema(BaseModel):
    company_id: int


class TelegramAuthSchema(BaseModel):
    # Описание структуры в документации Telegram:
    # https://core.telegram.org/widgets/login#receiving-authorization-data

    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str
