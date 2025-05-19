from enum import Enum


class CallTypeFilter(str, Enum):
    """
    Фильтр `allowed_call_types`.

    Класс содержит возможные значения фильтра,
    которые могут быть заданы для любой CRM или телефонии.
    """
    INBOUND_VALUE = 'in'
    OUTBOUND_VALUE = 'out'
