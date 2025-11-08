import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from config import config
from data.models import main_db
from integrations.amo_crm.keys_refresher import refresh_amocrm_keys


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


# Примеры job-ов
# scheduler.add_job(run_lesson_parser, "interval", seconds=lesson_parser_interval, next_run_time=datetime.now())
# scheduler.add_job(sync_students, "interval", seconds=60)
# scheduler.add_job(sync_tutors, "cron", hour=7, minute=0)

scheduler = BlockingScheduler(timezone=pytz.timezone(config.TIME_ZONE))
scheduler.add_job(job_refresh_amocrm_keys, "cron", hour=6, minute=0)


def main():
    logger.info('Запускаю jobs.py')
    job_refresh_amocrm_keys()
    scheduler.start()
    scheduler.shutdown()


if __name__ == "__main__":
    main()
