from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, ConfigDict


class TransactionPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    company_id: int
    user_id: Optional[int] = None
    payment_sum: Optional[int] = None
    payment_currency: Optional[str] = None
    minutes: int
    payment_type: str
    description: Optional[str] = None


class TransactionCreateSchema(BaseModel):
    company_id: int
    payment_sum: int
    payment_currency: str = 'RUB'
    minutes: int
    payment_type: str
    description: str
