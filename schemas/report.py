from datetime import datetime
from typing import Optional, Annotated, List

from pydantic import BaseModel, ConfigDict, Field


class ReportCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    integration_id: int
    description: str
    mode_template_id: Optional[int] = None


class ReportUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    integration_id: Optional[int] = None
    priority: int
    description: str
    sheet_id: Optional[str] = None
    settings: str
    filters: str
    crm_data: str
    final_model: str
    context: str
    active: bool


class ReportPartialUpdateSchema(BaseModel):
    name: Optional[str] = None
    priority: Optional[int] = None
    sheet_id: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[str] = None
    filters: Optional[str] = None
    crm_data: Optional[str] = None
    final_model: Optional[str] = None
    context: Optional[str] = None
    active: Optional[bool] = None
    is_archived: Optional[bool] = None



class ReportPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    name: str
    priority: int
    description: str
    integration_id: int
    sheet_id: Optional[str] = None
    settings: str
    filters: str
    crm_data: str
    final_model: str
    context: Optional[str] = None
    active: bool


class IntegrationTypeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    service_name: str


class ReportListItemPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    name: str
    description: str
    priority: int
    integration: IntegrationTypeSchema
    settings: str
    filters: str
    crm_data: str
    final_model: str
    context: Optional[str] = None
    active: bool


class CRMQuestionCreateSchema(BaseModel):
    entity_type: str
    crm_id: str
    name: str
    options: List[dict]


class ReportCRMQuestionsUpdateSchema(BaseModel):
    questions: List[CRMQuestionCreateSchema]
