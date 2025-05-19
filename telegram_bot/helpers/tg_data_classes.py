from enum import Enum


class StartData(str, Enum):
    """
    Возможные параметры в ссылке /start?...
    """
    activate = 'activate'
    get_transcript = 'get-transcript'
    bonus_from = 'BonusFrom'
    default_mode = 'DefaultMode'
