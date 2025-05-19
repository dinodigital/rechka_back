from pyrogram import filters
from config import config


def admin_filter(_, __, message):
    return message.from_user.id in config.ADMINS


def audio_video_filter(_, __, message):
    return message.audio or message.video or (message.document and ('audio' in message.document.mime_type or 'video' in message.document.mime_type))


def json_filter(_, __, message):
    return message.document and message.document.mime_type == "application/json"


admin_filter = filters.create(admin_filter)
audio_video_filter = filters.create(audio_video_filter)
json_filter = filters.create(json_filter)
