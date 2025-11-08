from json import JSONDecodeError

from pyrogram.types import Message

from config.const import JsonType
from modules.json_processor.integration import create_integration_with_json
from modules.json_processor.json_helpers import create_mode_with_json, create_report_with_json
from modules.json_processor.struct_checkers import get_dict_from_json


def process_json(message: Message) -> None:
    # Скачиваем json файл
    message.reply("Скачиваю json файл")
    file_path = message.download()

    # Парсим json файл в словарь
    try:
        full_json = get_dict_from_json(file_path)
    except JSONDecodeError:
        message.reply('Не удалось открыть файл. Проверьте структуру JSON.')
        return None

    json_type = full_json.get("type", "")

    if json_type == JsonType.create_mode:
        create_mode_with_json(message, full_json)
    elif json_type == JsonType.create_integration:
        create_integration_with_json(message, full_json)
    elif json_type == JsonType.create_report:
        create_report_with_json(message, full_json)

    return None
