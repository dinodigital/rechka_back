import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from config import config
from data.models import main_db
from integrations.amo_crm.keys_refresher import refresh_amocrm_keys
from modules.analytics import refresh_analytics_sheet
from modules.bot_users_uploader import sync_leads_to_google_sheets


def job_wrapper(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            main_db.close()
    return wrapper


@job_wrapper
def job_refresh_amocrm_keys():
    return refresh_amocrm_keys()


@job_wrapper
def job_refresh_analytics_sheet():
    return refresh_analytics_sheet()


# Примеры job-ов
# scheduler.add_job(run_lesson_parser, "interval", seconds=lesson_parser_interval, next_run_time=datetime.now())
# scheduler.add_job(sync_students, "interval", seconds=60)
# scheduler.add_job(sync_tutors, "cron", hour=7, minute=0)

scheduler = BlockingScheduler(timezone=pytz.timezone(config.TIME_ZONE))
scheduler.add_job(job_refresh_amocrm_keys, "cron", hour=6, minute=0)
scheduler.add_job(job_refresh_analytics_sheet, "interval", hours=1)
scheduler.add_job(sync_leads_to_google_sheets, "cron", hour=4, minute=0)

if __name__ == "__main__":
    logger.info("Запускаю jobs.py")
    job_refresh_amocrm_keys()
    job_refresh_analytics_sheet()
    scheduler.start()
    scheduler.shutdown()
