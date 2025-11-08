from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from data.models import ModeQuestionType, ModeQuestionCalcType


class ModeQuestionPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    is_active: bool
    report_id: int
    short_name: str
    calc_type: ModeQuestionCalcType
    column_index: int
    data: str
    context: Optional[str]
    question_text: str
    answer_type: ModeQuestionType
    answer_format: Optional[str]
    answer_options: Optional[str]
    variant_colors: Optional[str]


class ModeQuestionCreateSchema(BaseModel):
    is_active: bool
    report_id: int
    short_name: str
    calc_type: Optional[ModeQuestionCalcType] = ModeQuestionCalcType.AI
    column_index: int
    data: str
    context: str
    question_text: str
    answer_type: ModeQuestionType
    answer_format: Optional[str] = None
    answer_options: Optional[str] = None
    variant_colors: Optional[str] = None


class ModeQuestionUpdateSchema(BaseModel):
    is_active: bool
    short_name: str
    column_index: int
    data: str
    context: str
    question_text: str
    answer_format: Optional[str] = None
    answer_options: Optional[str] = None
    variant_colors: Optional[str] = None


class ModeQuestionPartialUpdateSchema(BaseModel):
    is_active: Optional[bool] = None
    short_name: Optional[str] = None
    column_index: Optional[int] = None
    data: Optional[str] = None
    context: Optional[str] = None
    question_text: Optional[str] = None
    answer_format: Optional[str] = None
    answer_options: Optional[str] = None
    variant_colors: Optional[str] = None
