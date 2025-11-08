from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class ModeAnswerPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    task_id: int
    question_id: int
    answer_text: Optional[str]


class ModeAnswerCreateSchema(BaseModel):
    task_id: int
    question_id: int
    answer_text: Optional[str] = None
