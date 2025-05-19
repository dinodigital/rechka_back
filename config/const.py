import itertools
from enum import Enum


class CBData(str, Enum):
    """
    Pyrogram Callback Data
    """
    buy_minute_pack = "buy-minute-pack"
    change_mode = "change-mode"


class JsonType(str, Enum):
    """
    Типы Json Объектов
    """
    create_mode = "create_mode"
    create_integration = "create_integration"
    create_report = "create_report"


class AmoNoteType(str, Enum):
    """
    Типы заметок AmoCRM в API.
    https://www.amocrm.ru/developers/content/crm_platform/events-and-notes#notes-types
    """
    COMMON = 'common'
    CALL_IN = 'call_in'
    CALL_OUT = 'call_out'
    SERVICE_MESSAGE = 'service_message'
    MESSAGE_CASHIER = 'message_cashier'
    GEOLOCATION = 'geolocation'
    SMS_IN = 'sms_in'
    SMS_OUT = 'sms_out'
    EXTENDED_SERVICE_MESSAGE = 'extended_service_message'
    ATTACHMENT = 'attachment'


"""
Типы заметок AmoCRM в вебхуке.
https://www.amocrm.ru/developers/content/digital_pipeline/salesbot#Действие-add_note
"""
AmoNoteTypeID = Enum(
    value='AmoNoteTypeID',
    names=itertools.chain.from_iterable(
        itertools.product(v, [k]) for k, v in {
            4: ['Обычное примечание', 'COMMON'],
            25: ['Сервисное примечание', 'SERVICE_MESSAGE'],
            10: ['Входящий', 'CALL_IN'],
            11: ['Исходящий', 'CALL_OUT'],
            102: ['Входящее СМС', 'SMS_IN'],
            103: ['Исходящее СМС', 'SMS_OUT'],
        }.items()
    ),
    type=int,
)


class CallbackAuthType(str, Enum):
    HTTP_BASIC = 'http_basic'
