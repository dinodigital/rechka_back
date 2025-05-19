import decimal
import hashlib
import json
from urllib import parse
from urllib.parse import urlparse

import config.config as cfg


def calculate_signature(*args) -> str:
    """Create signature MD5.
    """
    return hashlib.md5(':'.join(str(arg) for arg in args).encode()).hexdigest()


def parse_response(request: str) -> dict:
    """
    :param request: Link.
    :return: Dictionary.
    """
    params = {}

    for item in urlparse(request).query.split('&'):
        key, value = item.split('=')
        params[key] = value
    return params


def check_signature_result(
        order_number: int,  # invoice number
        received_sum: decimal,  # cost of goods, RU
        received_signature: hex,  # SignatureValue
        password: str  # Merchant password
) -> bool:
    signature = calculate_signature(received_sum, order_number, password)
    if signature.lower() == received_signature.lower():
        return True
    return False


def make_receipt(qty):
    """
    ЧЕК
    """
    return parse.quote(json.dumps({
        "sno": "usn_income",
        "items": [
            {
                "name": "Минуты анализа звонков",
                "quantity": qty,
                "sum": qty * cfg.PRICE_PER_MINUTE_IN_RUB,
                "cost": cfg.PRICE_PER_MINUTE_IN_RUB,
                "payment_method": "full_payment",
                "tax": "none"
            }
        ]
    }))


# Формирование URL переадресации пользователя на оплату.

def generate_payment_link(
        merchant_login: str,  # Merchant login
        merchant_password_1: str,  # Merchant password
        cost: decimal,  # Cost of goods, RU
        number: int,  # Invoice number
        description: str,  # Description of the purchase
        minutes_to_buy: int,
        is_test=0,
        robokassa_payment_url='https://auth.robokassa.ru/Merchant/Index.aspx',
) -> str:
    """URL for redirection of the customer to the service.
    """
    receipt = make_receipt(minutes_to_buy)
    signature = calculate_signature(
        merchant_login,
        cost,
        number,
        receipt,
        merchant_password_1
    )

    data = {
        'MerchantLogin': merchant_login,
        'OutSum': cost,
        'InvId': number,
        'Description': description,
        'SignatureValue': signature,
        'IsTest': is_test,
        'Receipt': parse.quote(receipt)
    }
    return f'{robokassa_payment_url}?{parse.urlencode(data)}'


# Получение уведомления об исполнении операции (ResultURL).

def result_payment(merchant_password_2: str, request: str) -> str:
    """Verification of notification (ResultURL).
    :param merchant_password_2:
    :param request: HTTP parameters.
    """
    param_request = parse_response(request)
    cost = param_request['OutSum']
    number = param_request['InvId']
    signature = param_request['SignatureValue']

    if check_signature_result(number, cost, signature, merchant_password_2):
        return f'OK{param_request["InvId"]}'
    return "bad sign"


def get_invoice_number(request: str):
    """
    Получаем номер инвойса
    """
    param_request = parse_response(request)
    return param_request['InvId']


# Проверка параметров в скрипте завершения операции (SuccessURL).

def check_success_payment(merchant_password_1: str, request: str) -> str:
    """ Verification of operation parameters ("cashier check") in SuccessURL script.
    :param merchant_password_1:
    :param request: HTTP parameters
    """
    param_request = parse_response(request)
    cost = param_request['OutSum']
    number = param_request['InvId']
    signature = param_request['SignatureValue']

    if check_signature_result(number, cost, signature, merchant_password_1):
        return "Thank you for using our service"
    return "bad sign"



