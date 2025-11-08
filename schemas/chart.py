from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field, ConfigDict


class ChartPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    report_id: int
    name: str
    order: int


class ChartCreateSchema(BaseModel):
    report_id: int
    name: str
    order: int


class ChartPartialUpdateSchema(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
