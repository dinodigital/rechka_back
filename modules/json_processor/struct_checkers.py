import json


def get_dict_from_json(path):
    """
    Получаем словарь по path к json файлу
    """
    with open(path, mode='r', encoding='utf-8') as f:
        data = json.load(f)

    return data

def is_create_mode_json(full_json: dict):
    # Проверка основных ключей
    if not all(key in full_json for key in ["mode_name", "params", "row"]):
        return False

    # Проверка ключей внутри params
    if not all(key in full_json["params"] for key in ["context", "final_model", "questions"]):
        return False

    # Проверка, что params>questions это список
    if not isinstance(full_json["params"]["questions"], list):
        return False

    # Проверка ключей внутри каждого элемента params>questions
    if not all("question" in item and "short_name" in item for item in full_json["params"]["questions"]):
        return False

    return True


def is_create_integration_json(full_json: dict):
    # Проверка, что значения по указанным ключам непустые.
    keys = ['service_name', 'account_id', 'telegram_id']
    return all(full_json.get(k) for k in keys)


def is_create_report_json(full_json: dict):
    # Проверка, что значения по указанным ключам непустые.
    keys = ['name', 'telegram_id', 'priority', 'mode', 'settings', 'filters', 'crm_data']
    return all(full_json.get(k) for k in keys)


def is_update_report_json(full_json: dict):
    # Проверка, что значения по указанным ключам непустые.
    keys = ['name', 'report_id', 'priority', 'mode', 'settings', 'filters', 'crm_data']
    return all(full_json.get(k) for k in keys)

