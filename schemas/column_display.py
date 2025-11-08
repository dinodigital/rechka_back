from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict


class ColumnDisplayPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    table_settings_id: int
    mode_question_id: int
    is_on: bool


class ColumnDisplayCreateSchema(BaseModel):
    table_settings_id: int
    mode_question_id: int
    is_on: bool


class ColumnDisplayUpdateSchema(BaseModel):
    is_on: bool
