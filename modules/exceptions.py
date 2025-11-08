
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


class LemurParseError(Exception):
    """
    Не удалось распарсить json-ответ от AssemblyAI.
    """

    def __init__(self, lemur_response: str, message: str):
        super().__init__(message)
        self.lemur_response = lemur_response


class TelegramBaseError(Exception):
    """
    Ошибки при работе с Telegram.
    """


class TelegramDataIsOutdated(TelegramBaseError):
    """
    Telegram-сессия неактуальна.
    """

class TelegramBadHashError(TelegramBaseError):
    """
    Некорректная контрольная сумма для данных, полученных в попытке авторизоваться через widget.
    """
