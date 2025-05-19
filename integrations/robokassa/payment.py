import decimal


from config import config as cfg
from data.models import Payment
from integrations.robokassa.robokassa_api import generate_payment_link


class RoboKassa:

    def __init__(self, is_test=cfg.ROBOKASSA_IS_TEST):
        self.merchant_login = cfg.ROBOKASSA_MERCHANT_LOGIN
        self.merchant_password_1 = cfg.ROBOKASSA_MERCHANT_PASS_1
        self.merchant_password_2 = cfg.ROBOKASSA_MERCHANT_PASS_2
        self.is_test = is_test
        self.robokassa_payment_url = 'https://auth.robokassa.ru/Merchant/Index.aspx'

    def generate_link(self, description: str, cost: int, invoice_number: int, minutes_to_buy: int):
        return generate_payment_link(
            merchant_login=self.merchant_login,
            merchant_password_1=self.merchant_password_1,
            description=description,
            cost=decimal.Decimal(cost),
            number=invoice_number,
            is_test=self.is_test,
            robokassa_payment_url=self.robokassa_payment_url,
            minutes_to_buy=minutes_to_buy
        )


def create_robokassa_payment_link(payment: Payment, minutes_to_buy: int):
    """
    Генерация ссылки на оплату через сервис Robokassa
    """
    description = f"Покупка пакета {minutes_to_buy} минут для анализа звонков"
    cost = payment.invoice_sum
    invoice_number = payment.id

    return RoboKassa().generate_link(description, cost, invoice_number, minutes_to_buy)
