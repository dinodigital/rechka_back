
class BaseBitrixException(Exception):
    """Базовый класс для Битрикс"""
    pass


class BadWebhookError(BaseBitrixException):
    """Некорректно настроенный вебхук"""
    pass


class DataIsNotReadyError(BaseBitrixException):
    """Данные еще не готовы для получения из Битрикс"""
    pass

