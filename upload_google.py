import json
import time
from datetime import datetime, timedelta

from loguru import logger

from data.models import Task
from integrations.gs_api.sheets import GSLoader


def upload_tasks():
    tasks = Task.select().where(
        (Task.status == Task.StatusChoices.IN_PROGRESS) &
        (Task.step == "uploaded_error")
    )

    logger.info(f"Начинаю выгружать звонки в гугл: всего {len(tasks)}")

    for task in tasks:
        if task.created < datetime.now() - timedelta(days=1):
            task.status = Task.StatusChoices.ERROR
            task.save()
            logger.info(f"Task ID {task.id} отклонен из-за истечения срока.")
            continue

        uploaded_data = json.loads(task.uploaded_data)
        try:
            GSLoader(task.user, task.mode).upload_values_as_row(uploaded_data)
        except Exception as e:
            logger.error(f"Ошибка при выгрузке в гугл таблицу Task {task.id}: {e}")
        else:
            task.status = Task.StatusChoices.DONE
            task.save()
        time.sleep(1)


def main():
    while True:
        upload_tasks()
        logger.info("Ожидание 1 мин перед следующей попыткой...")
        time.sleep(60)


if __name__ == "__main__":
    main()
