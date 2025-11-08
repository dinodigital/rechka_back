from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict


class TableViewSettingsPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    report_id: int
    user_id: int
    name: str


class TableViewSettingsCreateSchema(BaseModel):
    report_id: int
    name: str


class TableViewSettingsUpdateSchema(BaseModel):
    name: str
