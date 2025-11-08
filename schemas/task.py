from datetime import datetime
from typing import Optional, Annotated

from pydantic import BaseModel, Field, ConfigDict


class TaskPublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[int, Field(examples=[1])]
    created: datetime
    user_id: Optional[int] = None
    deal_id: Optional[int] = None
    mode_id: Optional[int] = None
    report_id: int

    step: Optional[str] = None
    status: Optional[str] = None
    error_details: Optional[str] = None
    is_archived: bool

    transcript_id: Optional[str] = None
    analyze_id: Optional[str] = None
    analyze_data: Optional[str] = None
    analyze_input_tokens: Optional[int] = None
    analyze_output_tokens: Optional[int] = None
    assembly_duration: Optional[int] = None
    initial_duration: Optional[int] = None
    duration_sec: Optional[int] = None
    file_url: Optional[str] = None
    data: str


class TaskUpdateSchema(BaseModel):
    is_archived: Optional[bool] = None


class TranscriptPublicSchema(BaseModel):
    task_id: int
    transcript: Optional[str] = None
