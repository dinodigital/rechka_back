from typing import List

from data.models import User, Mode


def get_short_name_list(params: dict) -> list:
    """Возвращает все short_name списком"""
    base_list = [item['short_name'] for item in params['questions']]

    out = []

    for item in base_list:
        if isinstance(item, List):
            for sub_item in item:
                out.append(sub_item)
        else:
            out.append(item)

    return out


def get_shortnames_by_user(db_user: User, mode: Mode = None):
    """
    Список short_name по db_user
    """
    if mode is not None:
        db_mode = mode
    else:
        db_mode: Mode = db_user.get_active_mode()
    params_with_shortnames = db_mode.get_full_json()['params']
    return get_short_name_list(params_with_shortnames)
