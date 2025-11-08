from typing import Tuple, Optional

from config import config as cfg
from data.models import Integration, User
from integrations.bitrix.bitrix_api import Bitrix24


def create_bitrix_contact_and_deal(
        db_user: User,
        username: str,
        phone_number: Optional[str] = None,
        raise_on_exists: bool = False,
) -> Tuple[int, int]:
    """
    Создает контакт и связанную с ним сделку в Битрикс24 Речки.

    Возвращает идентификаторы созданных карточек:
    (ID Контакта, ID Сделки).
    """
    integration = Integration.get_or_none(Integration.id == cfg.BITRIX24_RECHKA_INTEGRATION_ID)
    webhook_url = integration.get_decrypted_access_field('webhook_url')
    bx24 = Bitrix24(webhook_url)

    if raise_on_exists:
        contacts = bx24.get_contact_list(cfg.BITRIX24_CONTACT_TG_ID_FIELD_NAME, db_user.tg_id)
        if contacts:
            raise Exception('Контакт уже существует в Битрикс.')

    # Создаем контакт.
    contact_fields = {
        cfg.BITRIX24_CONTACT_TG_ID_FIELD_NAME: db_user.tg_id,
        cfg.BITRIX24_CONTACT_REFERRER_FIELD_NAME: db_user.invited_by or 0,
        'EMAIL': [{"VALUE": f'{username}@telegram.chatapp.online', "VALUE_TYPE": "MAILING"}],
    }
    if phone_number:
        contact_fields['PHONE'] = [{'VALUE': phone_number, 'VALUE_TYPE': 'WORK'}]

    deal_title = f'Лид из бота @{username}'
    contact_id = bx24.add_contact(contact_fields)

    # Создаем сделку и связываем с только что созданным контактом.
    deal_fields = {
        'CATEGORY_ID': cfg.BITRIX24_NEW_TG_USER_PIPELINE_ID,
        'STAGE_ID': cfg.BITRIX24_NEW_TG_USER_STAGE_ID,
        'TITLE': deal_title,
        'SOURCE_ID': cfg.BITRIX24_NEW_TG_USER_SOURCE_ID,
        'UTM_SOURCE': 'self_telegram_bot',
        'UTM_MEDIUM': 'bot_registration',
        'CONTACT_IDS': [contact_id],
    }
    deal_id = bx24.add_deal(deal_fields)

    return contact_id, deal_id
