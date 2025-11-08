import json
import re

from pydantic import BaseModel, Field
from typing import Optional, ClassVar, Any, List, Dict, Union

from starlette.datastructures import FormData


class AmoWebhook(BaseModel):
    """ Базовая модель вебхука AmoCRM """
    account_subdomain: str = Field(alias='account[subdomain]')
    account_id:        int = Field(alias='account[id]')


class BaseNoteAmoWebhook(AmoWebhook):
    text:     Optional[str] = None
    UNIQ:     Optional[str] = None
    LINK:     Optional[str] = None
    PHONE:    Optional[str] = None
    DURATION: Optional[int] = None
    SRC:      Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        self.parse_text_field()

    @staticmethod
    def parse_phone_field(phone: Union[str, int]) -> Optional[str]:
        if not phone:
            return None
        elif isinstance(phone, int):
            return str(phone)
        else:
            pattern = r'\s*\+?([\d\s()-]+).*'
            matches = re.findall(pattern, phone)
            return ''.join([x for x in matches[0] if x not in '( )-'])

    def parse_text_field(self):
        if self.text:
            try:
                text_data = json.loads(self.text)
                if isinstance(text_data, dict):
                    self.UNIQ = text_data.get('UNIQ')
                    self.LINK = text_data.get('LINK')
                    self.PHONE = self.parse_phone_field(text_data.get('PHONE'))
                    self.DURATION = int(text_data.get('DURATION')) if text_data.get('DURATION') is not None else None
                    self.SRC = text_data.get('SRC')
            except json.JSONDecodeError:
                pass


class ContactNoteAmoWebhook(BaseNoteAmoWebhook):
    entity:       ClassVar = "contacts"
    date_create:  Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][date_create]')
    main_user_id: Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][main_user_id]')
    note_type:    Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][note_type]')
    note_id:      Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][id]')
    timestamp_x:  Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][timestamp_x]')
    element_type: Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][element_type]')
    element_id:   Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][element_id]')
    text:         Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][text]')


class LeadNoteAmoWebhook(BaseNoteAmoWebhook):
    entity:       ClassVar = "leads"
    date_create:  Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][date_create]')
    main_user_id: Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][main_user_id]')
    note_type:    Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][note_type]')
    note_id:      Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][id]')
    timestamp_x:  Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][timestamp_x]')
    element_type: Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][element_type]')
    element_id:   Optional[int] = Field(default=None, alias=f'{entity}[note][0][note][element_id]')
    text:         Optional[str] = Field(default=None, alias=f'{entity}[note][0][note][text]')


def make_note_webhook(form_data: FormData) -> BaseNoteAmoWebhook | None:
    wh_types = {
        'leads[note][0][note][note_type]': LeadNoteAmoWebhook,
        'contacts[note][0][note][note_type]': ContactNoteAmoWebhook,
    }
    for key, model in wh_types.items():
        if key in form_data:
            return model.model_validate(form_data)
    return None


class AmoLead(BaseModel):
    name: str
    pipeline_id: int
    status_id: int
    responsible_user_id: int


# ----------------------------------------------------------------------------------------------------------------------
# API МОДЕЛИ
# ----------------------------------------------------------------------------------------------------------------------

class AuthRequestMixin(BaseModel):
    """
    Обязательные поля аутентификации.
    Например, в запросе на кастомный вебхук.
    """
    account_id: str
    telegram_id: int
    client_secret: str


class AuthRequest(AuthRequestMixin):
    pass


class CustomCallRequest(AuthRequestMixin):
    call_url: str
    call_id: Optional[str] = None
    report_id: Optional[int] = None
    callback_url: Optional[str] = None
    fields_to_export: Optional[List[Dict[str, Any]]] = None
    advance_transcript: Optional[bool] = False
    lead_id: Optional[str] = None
    consider_previous_call: Optional[bool] = False


class CustomTaskRequest(AuthRequestMixin):
    task_id: int
