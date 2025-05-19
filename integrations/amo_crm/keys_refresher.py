from loguru import logger

from data.models import Integration, IntegrationServiceName
from integrations.amo_crm.amo_api_core import AmoApiAuth


def get_valid_amocrm_integrations():
    """
    Возвращает список всех интеграций AmoCRM, у которых есть токен доступа.
    """
    integrations = Integration.select().where(Integration.service_name == IntegrationServiceName.AMOCRM)
    valid_integrations = [x for x in integrations if x.has_amo_access_token()]
    return valid_integrations


def refresh_amocrm_keys():
    """
    Функция используется для обновления токенов доступа для всех интеграций AmoCRM.
    """
    integrations = get_valid_amocrm_integrations()

    logger.info(f"Запускаю обновление токенов для {len(integrations)} интеграций")

    for integration in integrations:
        response = AmoApiAuth(integration, with_handle_auth=False).handle_auth()

        if response == "ok":
            logger.info(f"Обновил AmoCRM токен для интеграции id: {integration.id}")
        else:
            logger.error(f"Ошибка обновления токена для интеграции id: {integration.id}. response: {response}")

    logger.info(f"Обновление токенов завершено")


if __name__ == "__main__":
    refresh_amocrm_keys()
