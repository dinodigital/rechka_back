from datetime import datetime

import pytz

from config import config


def get_refresh_time(
        tz_name: str = config.TIME_ZONE,
        date_fmt: str = '%d.%m.%Y %H:%M:%S',
) -> str:
    """
    Возвращает текущие дату и время
    для часового пояса `tz_name`
    в формате `date_fmt`.
    """
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime(date_fmt)
