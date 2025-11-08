import os
import uuid
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends
from fastapi import UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_201_CREATED

from config import config as cfg
from routers.auth import get_current_active_user
from schemas.user import UserModel


router = APIRouter()


@router.post('/upload_files')
async def upload_user_file(
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
        upload_file: UploadFile = File(...),
) -> JSONResponse:

    # Разрешённые расширения файлов для загрузки (аудио и видео).
    allowed_extensions = {
        'audio/mpeg': '.mp3',
        'audio/aac': '.aac',
        'audio/wav': '.wav',
        'audio/x-wav': '.wav',
        'audio/ogg': '.ogg',
        'audio/flac': '.flac',
        'audio/mp4': '.m4a',
        'audio/x-m4a': '.m4a',
        'audio/mp4a-latm': '.m4a',
        'video/mp4': '.mp4',
        'video/x-msvideo': '.avi',
        'video/quicktime': '.mov',
        'video/x-ms-wmv': '.wmv',
        'video/x-matroska': '.mkv',
        'video/x-flv': '.flv',
        'video/webm': '.webm',
        'video/3gpp': '.3gp',
        'video/ogg': '.ogg',
    }
    # Максимальный размер загружаемого файла.
    max_file_size = 50 * 1024 * 1024  # 50 МБ

    # Проверка расширения файла.
    content_type = upload_file.content_type
    extension = Path(upload_file.filename).suffix.lower()
    if (content_type not in allowed_extensions
            or allowed_extensions[content_type] != extension):
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Недопустимый формат файла.')

    # Формируем уникальное имя файла.
    stem = Path(upload_file.filename).stem
    filename = f'{stem}_{uuid.uuid4().hex}{extension}'

    # Путь к файлу на диске.
    file_path = os.path.join(cfg.FASTAPI_STATIC_UPLOAD_DIR, filename)
    # URL для доступа извне.
    file_url = f'/static/upload/{filename}'

    file_size = 0

    try:
        async with aiofiles.open(file_path, mode='wb') as out_file:
            while chunk := await upload_file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > max_file_size:
                    raise HTTPException(HTTP_400_BAD_REQUEST, detail='Файл слишком большой.')
                await out_file.write(chunk)
    except HTTPException as ex:
        logger.error(f'Не удалось загрузить файл на сервер. {ex.detail}')
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    except Exception as ex:
        logger.error(f'Не удалось загрузить файл на сервер. Ошибка: {type(ex)} {ex}.')
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Ошибка при сохранении файла.')

    if file_size == 0:
        raise HTTPException(HTTP_400_BAD_REQUEST, detail='Файл пустой.')

    return JSONResponse(content={'url': file_url,
                                 'content_type': upload_file.content_type},
                        status_code=HTTP_201_CREATED)
