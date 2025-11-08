from enum import Enum
from typing import List

from integrations.const import CallTypeFilter


class Direction(int, Enum):
    """
    Возможные направления звонков Mango.
    """
    INBOUND = 1
    OUTBOUND = 2
    INTERNAL = 3

    @classmethod
    def get_rus(
            cls,
            direction: int,
    ) -> str:
        translations = {
            cls.INBOUND.value: 'Входящий',
            cls.OUTBOUND.value: 'Исходящий',
            cls.INTERNAL.value: 'Внутренний',
        }
        result = translations[direction]
        return result

    @classmethod
    def is_allowed_by_filters(
            cls,
            direction: int,
            allowed_call_types: List[str],
    ) -> bool:
        """
        Проверяет направление звонка`direction` по фильтру `allowed_call_types`.
        """
        if direction == cls.INBOUND and CallTypeFilter.INBOUND_VALUE not in allowed_call_types:
            return False
        if direction == cls.OUTBOUND and CallTypeFilter.OUTBOUND_VALUE not in allowed_call_types:
            return False
        if direction == cls.INTERNAL and CallTypeFilter.INTERNAL_VALUE not in allowed_call_types:
            return False
        return True
