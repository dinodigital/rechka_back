from loguru import logger

from config import config as cfg
from data.models import Payment, User
from telegram_bot.helpers import txt
from integrations.robokassa.robokassa_api import get_invoice_number, result_payment
from telegram_bot.apps import tg_sender


def process_result_url(request_body):
    response_url = f'{cfg.SERVER_LINK}/?{request_body.decode("utf-8")}'
    invoice_number: str = get_invoice_number(response_url)
    invoice_number: int = int(invoice_number)

    # Обновляем количество оплат в БД
    payment: Payment = Payment.get_or_none(id=invoice_number)
    if payment:
        payment.is_payed += 1
        payment.save()
    else:
        return logger.error("Платеж не обнаружен в БД")

    # Добавляем баланс пользователю в БД
    db_user: User = payment.user
    if db_user:
        db_user.company.add_balance(payment.seconds)
    else:
        return logger.error("Пользователь не обнаружен в БД")

    # Уведомляем о пополнении баланса
    with tg_sender:
        tg_sender.send_message(payment.user.tg_id, txt.balance_added(payment))
        tg_sender.send_message(cfg.ADMIN_CHAT_ID, f"💰 Новый платеж: {payment.invoice_sum} рублей от tg_id: {db_user.tg_id}")

    return result_payment(cfg.ROBOKASSA_MERCHANT_PASS_2, response_url)


