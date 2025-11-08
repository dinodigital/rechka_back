from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict



class ChartFilterPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    chart_id: int
    mode_question_id: int
    operation: str
    value: str


class ChartFilterCreateSchema(BaseModel):
    mode_question_id: int
    operation: str
    value: str


class ChartFilterUpdateSchema(BaseModel):
    operation: str
    value: str
