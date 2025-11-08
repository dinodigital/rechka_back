from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ModePublicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str]
    mode_id: Optional[str]
    params: Optional[str]
    sheet_id: Optional[str]
    insert_row: Optional[int]
    tg_link: Optional[str]
    full_json: Optional[str]

    created: datetime


class ModeCreateSchema(BaseModel):
    name: Optional[str]
    mode_id: Optional[str]
    params: Optional[str]
    sheet_id: Optional[str]
    insert_row: Optional[int] = 3
    tg_link: Optional[str]
    full_json: Optional[str]


class ModeUpdateSchema(BaseModel):
    name: Optional[str]
    mode_id: Optional[str]
    params: Optional[str]
    sheet_id: Optional[str]
    insert_row: Optional[int]
    tg_link: Optional[str]
    full_json: Optional[str]


class ModePartialUpdateSchema(BaseModel):
    name: Optional[str] = None
    mode_id: Optional[str] = None
    params: Optional[str] = None
    sheet_id: Optional[str] = None
    insert_row: Optional[int] = None
    tg_link: Optional[str] = None
    full_json: Optional[str] = None

