import base64
import os
import uuid
from typing import Optional

import requests
from loguru import logger
from pydub import AudioSegment
from pyrogram import Client
from pyrogram.types import Message
from requests import HTTPError
from retry import retry, retry_call

from config.config import DOWNLOADS_PATH


def check_status_code(status_code: int) -> bool:
    """
    Проеверка статус-кода запроса на успех
    :param status_code: int
    :return: True если запрос прошел успешно, иначе False
    """
    if 2 <= status_code / 100 < 3:
        return True
    return False


class Audiofile:

    def __init__(self):
        self.path = ""
        self.url = ""
        self.name = ""
        self.duration_in_sec = 0
        self.duration_in_min = 0
        self.duration_min_sec = ""

    @staticmethod
    def download_by_tg_file_id(cli: Client, tg_file_id):
        return cli.download_media(tg_file_id)

    @staticmethod
    def get_extension_by_content_type(content_type: str) -> str:
        extensions = {
            'audio/mpeg': '.mp3',
            'audio/aac': '.aac',
            'audio/wav': '.wav',
            'audio/x-wav': '.wav',
            'audio/ogg': '.ogg',
            'audio/flac': '.flac',
            'audio/mp4': '.m4a',
            'audio/x-m4a': '.m4a',
            'audio/mp4a-latm': '.m4a',
        }
        return extensions.get(content_type, '.unknown')

    def download_by_url(self, url, save_path=None, request_kwargs: Optional[dict] = None):
        if request_kwargs is None:
            request_kwargs = {}

        logger.info(f"Скачиваю аудиофайл по ссылке: {url}")
        try:
            response = requests.get(url, stream=True, **request_kwargs)
        except Exception as e:
            logger.error(f"Ошибка скачивания файла: {e}")
            raise HTTPError

        if not check_status_code(response.status_code):
            logger.error(f"Ошибка скачивания файла (статус {response.status_code}): {response.text}")
            raise HTTPError

        # Определение расширения файла на основе MIME-типа
        content_type = response.headers.get('Content-Type')
        content_type_small_letter = response.headers.get('content-type')
        logger.info(f"Заголовки ответа: {response.headers}")
        logger.info(f"MIME-тип: {content_type}")
        logger.info(f"MIME-тип (*): {content_type_small_letter}")
        extension = self.get_extension_by_content_type(content_type)
        logger.info(f"Расширение файла: {extension}")

        # Если путь сохранения не указан, создаем на основе URL и определенного расширения
        if save_path is None:
            save_path = os.path.join(DOWNLOADS_PATH, f'audio_{uuid.uuid4()}{extension}')

        logger.info(f"Путь файла: {save_path}")

        file_is_empty = True
        with open(save_path, mode='wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                # chunk может быть равен b''
                if chunk:
                    file_is_empty = False
                file.write(chunk)

        # Получили код 200, но содержимое (content) == b''.
        if file_is_empty:
            raise HTTPError

        return save_path

    def save_file_by_sipuni_headers(self, data, headers):
        # Определение расширения файла на основе MIME-типа
        content_type = headers.get('Content-Type')
        logger.info(f"Sipuni: MIME-тип: {content_type}")
        extension = self.get_extension_by_content_type(content_type)
        logger.info(f"Расширение файла: {extension}")

        # Если путь сохранения не указан, создаем на основе URL и определенного расширения
        save_path = os.path.join(DOWNLOADS_PATH, f'audio_{uuid.uuid4()}{extension}')

        logger.info(f"Sipuni: Путь файла: {save_path}")

        with open(save_path, mode='wb') as file:
            file.write(data)

        return save_path

    @staticmethod
    def _seconds_to_min_sec(seconds):
        """
        Длительность звонка в секундах выводит вида мин:сек
        """
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes}:{remaining_seconds:02}"

    @staticmethod
    @retry(tries=3)
    def _get_audio_duration_in_seconds(path):
        """
        Длительность аудиофайла в секундах
        """
        try:
            audio = AudioSegment.from_file(path)
            duration_seconds = len(audio) / 1000.0  # Преобразование миллисекунд в секунды
            return int(duration_seconds)
        except Exception as e:
            logger.error(f"[-] Ошибка обработки длительности аудиофайла в секундах. Детали: {e}")
            raise Exception

    def _load_durations(self, path):
        """
        Загружает длительности аудиофайлов
        """
        self.duration_in_sec = self._get_audio_duration_in_seconds(path)
        self.duration_in_min = round(self.duration_in_sec / 60, 2)
        self.duration_min_sec = self._seconds_to_min_sec(self.duration_in_sec)
        return self

    def load_from_tg_message_with_audio(self, cli, message_with_audio: Message):
        """
        Наполняет экземпляр класса данными из telegram сообщения
        """
        from helpers.tg_helpers import get_tg_file_id_from_message, get_tg_file_name

        tg_file_id: str = get_tg_file_id_from_message(message_with_audio)

        self.path = self.download_by_tg_file_id(cli, tg_file_id)
        self._load_durations(self.path)
        self.name = get_tg_file_name(message_with_audio)
        self.url = tg_file_id

        return self

    def load_from_url(self, url, name: Optional[str] = None):
        """
        Наполняет экземпляр класса данными из url
        """
        if name is None:
            name = str(uuid.uuid4())

        self.path = self.download_by_url(url)
        self._load_durations(self.path)
        self.name = name
        self.url = url

        return self

    def load_from_sipuni(self, data, headers, name: Optional[str] = None):
        """
        Наполняет экземпляр класса данными из url
        """
        if name is None:
            name = str(uuid.uuid4())

        self.path = self.save_file_by_sipuni_headers(data, headers)
        self._load_durations(self.path)
        self.name = name
        self.url = ""

        return self

    @staticmethod
    def get_a1_access_token(company_id: str, api_key: str, encoding: str = 'utf-8') -> str:
        """
        Получение токена для выполнения запросов к a1.
        """
        url = 'https://vats.a1.by/crm-api/open-api/v1/auth/tokens'
        auth_header = base64.b64encode(f'{company_id}:{api_key}'.encode(encoding)).decode(encoding)
        headers = {
            'Authorization': auth_header,
        }
        response = requests.get(url, headers=headers)
        access_token = response.json()['access_token']
        return access_token

    def load_from_a1(self, url: str, company_id: str, api_key: str, name: Optional[str] = None):
        """
        Загружает файл по ссылке url для АТС a1.by.
        Наполняет экземпляр класса данными из url
        """
        if name is None:
            name = str(uuid.uuid4())

        record_name = url.split('/record-crm/')[-1]
        file_url = f'https://vats.a1.by/crm-api/open-api/v1/record?company_id={company_id}&filename={record_name}'

        access_token = retry_call(
            self.get_a1_access_token, fargs=[company_id, api_key],
            tries=3, delay=1, backoff=4, logger=logger,
        )
        request_kwargs = {
            'headers': {'Authentication': access_token},
        }
        self.path = retry_call(
            self.download_by_url, fargs=[file_url], fkwargs={'request_kwargs': request_kwargs},
            tries=3, delay=1, backoff=4, logger=logger,
        )

        self._load_durations(self.path)
        self.name = name
        self.url = url

        return self
