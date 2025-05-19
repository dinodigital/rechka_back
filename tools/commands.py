from typing import Optional, List

from loguru import logger

from data.models import main_db, Mode, Integration, IntegrationServiceName, User
from integrations.amo_crm.amo_api_core import AmoApi
from integrations.bitrix.bitrix_api import Bitrix24
from routers.lk import get_password_hash


def update_model_for_all_modes(model_name: str):
    """
    Изменяет модель нейронной сети для всех режимов.
    """
    logger.info(f'Меняем модель нейронной сети для всех режимов на {model_name}.')

    with main_db:
        modes = Mode.select()
        for mode in modes:
            params = mode.get_params()
            old_model_name = params.get('final_model')
            if old_model_name != model_name:
                params['final_model'] = model_name
                mode.update_params(params)
                logger.info(f'Поменяли {old_model_name} на {model_name} для Mode {mode}.')

    logger.info(f'Завершили обновление модели.')


def update_params_for_default_modes(params: dict, mode_id_prefix: str = 'default'):
    """
    Обновляет params для всех режимов с отчетами по умолчанию.
    """
    logger.info(f'Меняем params для режимов с отчетами по умолчанию.')

    with main_db:
        modes = Mode.select().where(Mode.mode_id.startswith(mode_id_prefix))
        for mode in modes:
            mode.update_params(params)
            logger.info(f'Обновили params для Mode {mode}.')

    logger.info(f'Завершили обновление params.')


def parse_bitrix_custom_fields(integration_id: int, language: str = 'ru') -> Optional[List[dict]]:
    """
    Парсит список пользовательских полей сделок для указанной интеграции Bitrix24.
    """
    with main_db:
        integration = Integration.get_or_none(Integration.id == integration_id)

    if integration is None:
        logger.error(f'[-] Парсинг пользовательских полей сделок. '
                     f'Интеграция не найдена. ID: {integration_id}.')
        return None

    if integration.service_name != IntegrationServiceName.BITRIX24:
        logger.error(f'[-] Парсинг пользовательских полей сделок. '
                     f'Некорректный тип интеграции: "{integration.service_name}".')
        return None

    logger.info(f'Парсим кастомные поля сделок. ID интеграции: {integration_id}.')

    webhook_url = integration.get_decrypted_access_field('webhook_url')
    bx24 = Bitrix24(webhook_url)
    data = bx24.parse_bitrix_custom_fields(language)

    logger.info(f'Парсинг кастомных полей сделок завершен. Получено полей: {len(data)}.')

    return data


def parse_amo_leads_custom_fields(integration_id: int) -> Optional[List[dict]]:

    with main_db:
        integration = Integration.get_or_none(Integration.id == integration_id)

    if integration is None:
        logger.error(f'[-] Парсинг пользовательских полей сделок. '
                     f'Интеграция не найдена. ID: {integration_id}.')
        return None

    if integration.service_name != IntegrationServiceName.AMOCRM:
        logger.error(f'[-] Парсинг пользовательских полей сделок. '
                     f'Некорректный тип интеграции: "{integration.service_name}".')
        return None

    amo = AmoApi(integration)

    logger.info(f'Парсим кастомные поля сделок. ID интеграции: {integration_id}.')
    data = amo.get_leads_custom_fields()

    logger.info(f'Парсинг кастомных полей сделок завершен. Получено полей: {len(data)}.')

    return data


def parse_bitrix_funnels_and_stages(integration_id: int) -> Optional[str]:
    """
    Выводит ID воронок (включая основную) и этапы сделок/лидов в Битрикс24.
    """
    with main_db:
        integration = Integration.get_or_none(Integration.id == integration_id)

    if integration is None:
        logger.error(f'[-] Парсинг воронок и этапов. '
                     f'Интеграция не найдена. ID: {integration_id}.')
        return None

    if integration.service_name != IntegrationServiceName.BITRIX24:
        logger.error(f'[-] Парсинг воронок и этапов. '
                     f'Некорректный тип интеграции: "{integration.service_name}".')
        return None

    webhook_url = integration.get_decrypted_access_field('webhook_url')
    bx24 = Bitrix24(webhook_url)

    result = ''

    logger.info(f'Получаем список воронок для {bx24.domain}.')
    funnels = bx24.get_funnels_with_stages()
    for funnel in funnels:
        result += f"Воронка (id: {funnel['id']}): {funnel['name']}\n"
        for stage in funnel['stages']:
            result += f"  Этап (id: {stage['STATUS_ID']}): {stage['NAME']}\n"
        result += '\n'

    result += "Этапы лидов:\n"
    logger.info('Получаем этапы лидов (они не привязаны к воронкам)')
    lead_statuses = bx24.get_status_list('STATUS')
    for status in lead_statuses:
        result += f"  Этап (id: {status['STATUS_ID']}): {status['NAME']}\n"

    return result


def update_password(user_id: int, new_password: str):
    with main_db.atomic():
        user = User.get(User.id == user_id)
        user.hashed_password = get_password_hash(new_password)
        user.save()


def main():
    update_password(1764, "Sergio123$")


if __name__ == '__main__':
    main()
