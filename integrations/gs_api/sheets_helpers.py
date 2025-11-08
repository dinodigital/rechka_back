from typing import List


def get_short_name_list(short_names: list) -> list:
    """Возвращает все short_name списком"""
    out = []

    for item in short_names:
        if isinstance(item, List):
            for sub_item in item:
                out.append(sub_item)
        else:
            out.append(item)

    return out
