
class IntegrationBaseError(Exception):
    """
    Исключения, связанные с созданием и обновлением интеграций.
    """


class IntegrationConnectError(IntegrationBaseError):
    """
    Не удалось подключиться к CRM/телефонии.
    """


class ObjectNotFoundError(IntegrationBaseError):
    """
    Интеграция или связанный с ней объект не найден.
    """


class IntegrationExistsError(IntegrationBaseError):
    """
    Интеграция с такими параметрами уже существует.
    """
