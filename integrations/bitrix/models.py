import itertools
from enum import Enum
from typing import List

from integrations.const import CallTypeFilter


class CRMEntityType(str, Enum):
    """
    Возможные значения поля `CRM_ENTITY_TYPE` в структуре, возвращаемой Bitrix24 по API.
    См. метод `Bitrix24.get_call_info()`.

    https://dev.1c-bitrix.ru/api_d7/bitrix/crm/crm_owner_type/identifiers.php
    """
    CONTACT = 'CONTACT'
    LEAD = 'LEAD'
    DEAL = 'DEAL'
    COMPANY = 'COMPANY'
    INVOICE = 'INVOICE'
    QUOTE = 'QUOTE'
    ORDER = 'ORDER'
    SMART_INVOICE = 'SMART_INVOICE'


"""
Тип объекта CRM.
https://apidocs.bitrix24.ru/api-reference/crm/data-types.html#object_type
"""
CRMEntityTypeID = Enum(
    value='CRMEntityTypeID',
    names=itertools.chain.from_iterable(
        itertools.product(v, [k]) for k, v in {
            1: ['Лид', 'LEAD'],
            2: ['Сделка', 'DEAL'],
            3: ['Контакт', 'CONTACT'],
            4: ['Компания', 'COMPANY'],
            5: ['Счет (старый)', 'INVOICE'],
            31: ['Счет (новый)', 'SMART_INVOICE'],
            7: ['Предложение', 'QUOTE'],
            8: ['Реквизит', 'REQUISITE'],
            14: ['Заказ', 'ORDER'],
            128: ['Смарт-процесс', 'DYNAMIC_128'],
        }.items()
    ),
    type=int,
)


class CallType(str, Enum):
    """
    Тип звонка Bitrix24.
    https://dev.1c-bitrix.ru/rest_help/scope_telephony/codes_and_types.php#call_type
    """
    OUTBOUND = '1'
    INBOUND = '2'
    INBOUND_WITH_FORWARDING = '3'
    CALLBACK = '4'

    @classmethod
    def get_readable_type(cls, call_type: str) -> str:
        """
        Возвращает понятное описание типа звонка на русском языке.

        :param call_type: Тип звонка ('1', '2', '3', или '4')
        :return: Описание типа звонка на русском языке
        """
        if call_type == cls.OUTBOUND:
            return "Исходящий"
        elif call_type == cls.INBOUND:
            return "Входящий"
        elif call_type == cls.INBOUND_WITH_FORWARDING:
            return "Входящий с переадресацией"
        elif call_type == cls.CALLBACK:
            return "Обратный звонок"
        else:
            return "Неизвестный тип звонка"

    @classmethod
    def is_allowed_by_filters(cls, call_type: str, filter_values: List[str]) -> bool:
        """
        Проверяет, разрешен ли переданный вебхуком тип звонка `call_type`.

        Список разрешенных типов формируется из `filter_values` (см. фильтр `allowed_call_types` конфига интеграции).
        Фильтр содержит одно или несколько названий направлений, которые стоит обрабатывать.
        Каждое такое направление означает один или несколько типов звонков. То есть:
        in = INBOUND + INBOUND_WITH_FORWARDING + CALLBACK
        out = OUTBOUND
        """
        allowed = []

        if CallTypeFilter.INBOUND_VALUE in filter_values:
            allowed.extend((cls.INBOUND,
                            cls.INBOUND_WITH_FORWARDING,
                            cls.CALLBACK))

        if CallTypeFilter.OUTBOUND_VALUE in filter_values:
            allowed.append(cls.OUTBOUND)

        is_allowed = call_type in allowed
        return is_allowed
