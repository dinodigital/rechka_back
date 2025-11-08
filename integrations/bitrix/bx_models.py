from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class BxWhData(BaseModel):
    CALL_DURATION: Optional[int] = None
    CALL_FAILED_CODE: Optional[str] = None
    CALL_FAILED_REASON: Optional[str] = None
    CALL_ID: Optional[str] = None
    CALL_START_DATE: Optional[datetime] = None
    CALL_TYPE: Optional[str] = None
    COST: Optional[float] = None
    COST_CURRENCY: Optional[str] = None
    CRM_ACTIVITY_ID: Optional[int] = None # Идентификатор дела CRM, созданного на основании звонка.
    PHONE_NUMBER: Optional[str] = None
    PORTAL_NUMBER: Optional[str] = None
    PORTAL_USER_ID: Optional[int] = None
