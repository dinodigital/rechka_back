from typing import Annotated, Optional

from pydantic import BaseModel, Field, ConfigDict

from data.models import ChartMetricType


class ChartParameterPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    chart_id: int
    mode_question_id: int
    color: str
    data_type: ChartMetricType
    metric_operation: str
    metric_condition: Optional[str] = None
    is_hidden: bool


class ChartParameterCreateSchema(BaseModel):
    mode_question_id: int
    color: str
    data_type: ChartMetricType
    metric_operation: str
    metric_condition: Optional[str] = None
    is_hidden: bool


class ChartParameterPartialUpdateSchema(BaseModel):
    mode_question_id: Optional[int] = None
    color: Optional[str] = None
    data_type: Optional[ChartMetricType] = None
    metric_operation: Optional[str] = None
    metric_condition: Optional[str] = None
    is_hidden: Optional[bool] = None


class ChartParameterDataPublicSchema(ChartParameterPublicSchema):
    # Координаты для отображения на графике.
    data: Optional[list] = None
