from typing import Annotated, Optional

from pydantic import BaseModel, Field, model_validator


class CallAnalyzeCreateSchema(BaseModel):
    report_id: Annotated[int, Field(examples=[1])]
    call_url: Optional[str] = None
    transcript_id: Optional[str] = None

    @model_validator(mode='before')
    def check_either_url_or_transcript_id(cls, data: dict):
        call_url = data.get('call_url')
        transcript_id = data.get('transcript_id')

        if call_url is None and transcript_id is None or (call_url is not None and transcript_id is not None):
            raise ValueError("Either 'call_url' or 'transcript_id' must be provided, but not both or none.")

        return data
