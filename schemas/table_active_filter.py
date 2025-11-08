from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict



class TableActiveFilterPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    table_settings_id: int
    mode_question_id: int
    operation: str
    value: str


class TableActiveFilterCreateSchema(BaseModel):
    mode_question_id: int
    operation: str
    value: str


class TableActiveFilterUpdateSchema(BaseModel):
    operation: str
    value: str
