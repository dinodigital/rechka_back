from pyrogram.types import Message
from loguru import logger

from data.models import User, Payment, Mode, Task
import config.config as cfg
from telegram_bot.helpers.tg_data_classes import StartData

first_message = f"""<b>Добро пожаловать!</b>

<b>Речка Ai</b> - это искусственный интеллект для анализа звонков. Бот анализирует звонки и делает по ним отчет.

<b>Как это работает</b>
1. Вы присылаете аудиозапись звонка
2. Бот присылает анализ и загружает его в Google таблицу

Мы можем настроить бота под ваш индивидуальный запрос для этого напишите нам в @{cfg.RECHKA_CHAT_USERNAME}"""

free_minutes_present = (f"🎁 <b>Вам подарок</b>\n"
                        f"\n"
                        f"{cfg.FREE_MINUTES} бесплатных минут для тестирования возможностей бота.\n"
                        f"\n"
                        f"↘️ <i>Пришлите аудиозапись звонка</i>")


def admin_balance_added(minutes):
    return f"➕ <b>Баланс пополнен</b> на <b>{minutes}</b> минут"


def cabinet(db_user: User):
    db_mode = db_user.get_active_mode()
    if db_user.seconds_balance is None:
        seconds_balance = 0
        logger.error(f"[-] Ошибка получения баланса секунд пользователя (None).")
    else:
        seconds_balance = db_user.seconds_balance
    return f"""👤 <b>Личный кабинет</b> {db_user.tg_id}

<b>Баланс:</b> {round(seconds_balance / 60, 1)} минут
<b>Google таблица:</b> <a href="{db_mode.sheet_url}"> Открыть → </a>

↘️ <i>Режим бота (<a href="https://telegra.ph/Rezhimy-SPEECHka-bot-10-09">что это?</a>)</i>"""


error = "Какая-то ошибка. Пробую еще раз."
error_try_again = "Какая-то ошибка. Пришлите аудиофайл заново."
error_no_db_user = "Бот вас не узнал. Свяжитесь с администратором @gorbunov."
error_unsupported_ai_model = "Неподдерживаемая нейросетевая модель. Обратитесь к администратору."


def mode_created(db_mode: Mode):
    return (f"✅ Режим <b>{db_mode.name}</b> успешно создан\n"
            f"\n"
            f"Регистрация клиента по ссылке:\n"
            f"{db_mode.tg_link}\n"
            f"\n"
            f"ID для Report: `{db_mode.id}`\n"
            f"ID активации: `{db_mode.mode_id}`")


def analyze_duration_min(audio_duration_in_sec):
    """
    Длительность анализа аудиофайла
    """
    submission_max = 20
    transcription_max = audio_duration_in_sec * 0.30
    t_max = submission_max + transcription_max
    rounded_seconds = round(t_max / 30) * 30
    rounded_minutes = rounded_seconds // 60

    text = (f"⏳ Анализирую аудиофайл\n"
            f"\n"
            f"<i>Транскрибация и анализ аудиофайла займет ~{rounded_minutes} мин. Ожидайте.</i>")

    return text


def request_payment(db_user_minutes_balance: float, minutes_to_go: float):
    txt = f"""⚠️ <b>Пополните баланс</b>

У вас на балансе <b>{db_user_minutes_balance}</b> минут, а для анализа присланной аудиозаписи необходимо <b>{minutes_to_go}</b> минут. Пополните баланс, чтобы продолжить анализировать звонки.

<i>Если у вас специфическая задача - свяжитесь с нами (@gorbunov, @pasha_kotoff), и мы разработаем для вас индивидуальное решение</i>

↘️ Выберите пакет минут
"""
    return txt


def request_payment_light(db_user_minutes_balance: float, minutes_to_go: float):
    txt = f"""⚠️ <b>Пополните баланс</b>

У вас на балансе <b>{db_user_minutes_balance}</b> минут, а для анализа присланной аудиозаписи необходимо <b>{minutes_to_go}</b> минут. Пополните баланс, чтобы продолжить анализировать звонки.

<b>Чтобы пополнить баланс - напишите @rechkaai</b>

<i>Если у вас специфическая задача - свяжитесь с нами (@gorbunov, @pasha_kotoff), и мы разработаем для вас индивидуальное решение</i>
"""
    return txt


def balance_added(db_payment: Payment):
    txt = f"""✅ <b>Баланс пополнен</b>

<b>{db_payment.minutes}</b> мин. зачислено на ваш баланс. Баланс доступен в личном кабинете по команде /start
"""
    return txt


def your_payment_link(minutes_to_buy):
    txt = f"""<b>Покупка {minutes_to_buy} минут</b>

Для покупки пакета минут совершите оплату через сервис Robokassa. После оплаты мы зачислим минуты на ваш баланс. 

<i>Если у вас возникнут трудности с оплатой - напишите нам (@gorbunov, @pasha_kotoff) </i>

↘️
"""
    return txt


def mode_activated(db_mode):
    txt = (f"Активирован режим <b>{db_mode.name}</b>\n"
           f"\n"
           f"Ссылка на отчет:\n"
           f"{db_mode.sheet_url}")
    return txt


def mode_activated_admin_msg(db_mode: Mode, client_tg_id: int):
    txt = (f"Пользователю с tg_id <b>{client_tg_id}</b> активирован режим <b>{db_mode.name}</b>\n"
           f"\n"
           f"Ссылка на отчет:\n"
           f"{db_mode.sheet_url}")
    return txt


def admin_call_report(username, db_user: User, db_task: Task):
    cost_price = round(3 * db_task.duration_sec / 60, 2)

    text = (f"☑️ Звонок проанализирован\n"
            f"\n"
            f"👤 {username}\n"
            f"╠ tg_id: {db_user.tg_id}\n"
            f"╠ режим: {db_user.mode_id}\n"
            f"╚ баланс: {db_user.seconds_balance} сек\n"
            f"\n"
            f"📞\n"
            f"╠ длительность: {db_task.duration_sec} сек\n"
            f"╚ себес: ~{cost_price}₽\n"
            f"\n"
            f"<i>transcript_id:</i>\n"
            f"<i>{db_task.transcript_id}</i>")
    return text


def referral_registered(message: Message):
    full_name = f'{message.from_user.first_name} {message.from_user.last_name}'
    username = f'@{message.from_user.username}' if message.from_user.username else '-'

    text = (f"➕👤 У вас новый реферал\n"
            f"╠ ID: {message.from_user.id}\n"
            f"╠ имя: {full_name}\n"
            f"╚ username: {username}")
    return text


def make_ref_link(tg_id: int):
    return f"{cfg.BOT_LINK}?start={StartData.bonus_from}_{tg_id}"


def partner_cabinet(db_user: User):
    referrals_count = User.select().where(User.invited_by == db_user.tg_id).count()

    txt = (f"<b>Партнерский кабинет</b>\n"
           f"\n"
           f"У вас <b>{referrals_count}</b> рефералов\n"
           f"\n"
           f"Ваша партнерская ссылка:\n"
           f"{make_ref_link(db_user.tg_id)}")
    return txt
