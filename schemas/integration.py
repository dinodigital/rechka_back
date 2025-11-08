from typing import Annotated, Dict, Optional, List

from pydantic import BaseModel, ConfigDict, Field

from data.models import IntegrationServiceName


class IntegrationPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    service_name: IntegrationServiceName
    account_id: str
    data: str
    company_id: int


class IntegrationCreateSchema(BaseModel):
    """
    Схема для создания интеграции.
    """
    model_config = ConfigDict(from_attributes=True)

    service_name: IntegrationServiceName
    account_id: str
    telegram_id: Optional[int] = None
    company_id: int
    data: Dict


class IntegrationUpdateSchema(BaseModel):
    """
    Схема для обновления интеграции.
    """
    model_config = ConfigDict(from_attributes=True)

    telegram_id: Optional[int] = None
    account_id: str
    company_id: int
    data: Dict


class CRMUserPublicSchema(BaseModel):
    """
    Пользователь CRM-системы (AmoCRM, Bitrix24, SipUni).
    """
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, Field(examples=['1'])]
    name: str


class CRMFieldPublicSchema(BaseModel):
    """
    Поля CRM/телефонии. Системные + пользовательские.
    """
    id: Annotated[str, Field(examples=['1'])]
    name: str
    options: Optional[List[dict]] = None


class PipelinePublicSchema(BaseModel):
    """
    Воронки с этапами.
    """
    id: Annotated[int, Field(examples=[1])]
    name: str
    statuses: Optional[List[dict]] = None

