from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class CompanyPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    name: str
    firm_name: Optional[str] = None

    # Баланс компании могут видеть:
    # - системный администратор;
    # - администратор компании;
    # - интегратор компании.
    seconds_balance: int


class CompanyExtendedPublicSchema(CompanyPublicSchema):
    bitrix_company_id: Optional[str] = None
    users_count: int


class CompanyPartialUpdateSchema(BaseModel):
    name: Optional[str] = None
    firm_name: Optional[str] = None
    bitrix_company_id: Optional[str] = None
