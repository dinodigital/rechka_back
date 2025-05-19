from enum import Enum
from typing import List

from integrations.const import CallTypeFilter


class Direction(str, Enum):
    """
    Возможные направления звонков Билайн.
    """
    INBOUND = 'INBOUND'
    OUTBOUND = 'OUTBOUND'

    @classmethod
    def get_rus(cls, direction: str) -> str:
        translations = {
            cls.INBOUND.value: 'Входящий',
            cls.OUTBOUND.value: 'Исходящий',
        }
        result = translations[direction]
        return result

    @classmethod
    def is_allowed_by_filters(cls, direction: str, allowed_call_types: List[str]) -> bool:
        """
        Проверяет направление звонка`direction` по фильтру `allowed_call_types`.
        """
        if direction == cls.INBOUND and CallTypeFilter.INBOUND_VALUE not in allowed_call_types:
            return False
        if direction == cls.OUTBOUND and CallTypeFilter.OUTBOUND_VALUE not in allowed_call_types:
            return False
        return True
