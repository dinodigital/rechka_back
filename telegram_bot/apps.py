from pyrogram import Client

from config import config as cfg

plugins = dict(root="telegram_bot/handlers")

main_app = Client(
    cfg.BOT_APP_NAME,
    api_id=cfg.BOT_API_ID,
    api_hash=cfg.BOT_API_HASH,
    bot_token=cfg.BOT_TOKEN,
    plugins=plugins
)

tg_sender = Client(
    cfg.SENDER_APP_NAME,
    api_id=cfg.BOT_API_ID,
    api_hash=cfg.BOT_API_HASH,
    bot_token=cfg.BOT_TOKEN
)
