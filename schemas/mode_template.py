from typing import Annotated, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ModeTemplatePublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    name: str
    final_model: str
    context: Optional[str] = None


class ModeTemplateCreateSchema(BaseModel):
    name: str
    report_id: int


class ModeTemplateUpdateSchema(BaseModel):
    name: str
    final_model: str
    context: Union[str, None] = None
