from typing import Tuple, Optional

from config import config as cfg
from data.models import Integration, User
from integrations.bitrix.bitrix_api import Bitrix24


def create_bitrix_contact_and_deal(
        db_user: User,
        phone_number: str,
        username: Optional[str] = None,
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
        'PHONE': [{'VALUE': phone_number, 'VALUE_TYPE': 'WORK'}],
        cfg.BITRIX24_CONTACT_REFERRER_FIELD_NAME: db_user.invited_by or 0,
    }
    if username:
        user_bx_email = f'{username}@telegram.chatapp.online'
        contact_fields['EMAIL'] = [{"VALUE": user_bx_email, "VALUE_TYPE": "MAILING"}]
    contact_id = bx24.add_contact(contact_fields)

    # Создаем сделку и связываем с только что созданным контактом.
    deal_fields = {
        'CATEGORY_ID': cfg.BITRIX24_NEW_TG_USER_PIPELINE_ID,
        'STAGE_ID': cfg.BITRIX24_NEW_TG_USER_STAGE_ID,
        'TITLE': f'Лид из бота @{phone_number}',
        'SOURCE_ID': cfg.BITRIX24_NEW_TG_USER_SOURCE_ID,
        'UTM_SOURCE': 'self_telegram_bot',
        'UTM_MEDIUM': 'bot_registration',
        'CONTACT_IDS': [contact_id],
    }
    deal_id = bx24.add_deal(deal_fields)

    return contact_id, deal_id
