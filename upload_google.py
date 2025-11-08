import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List

from loguru import logger

from config import config as cfg
from data.models import GSpreadTask, Task, Report
from integrations.gs_api.sheets import SheetsApi


def prepare_row(values_to_upload: str) -> List[str]:

    row = json.loads(values_to_upload)

    # Распаковываем значения ['-'] в '-'.
    for col_idx in range(len(row)):
        col_value = row[col_idx]
        if isinstance(col_value, (list, tuple,)):
            if len(col_value) == 1:
                if len(col_value[0]) == 1:
                    row[col_idx] = col_value[0]
                else:
                    row[col_idx] = f'- {col_value[0]}'
            else:
                row[col_idx] = '\n'.join([f'– {x}' for x in col_value])

    return row


def update_google_report(
        report: Report,
        chunk_size: int = 2000,
):
    """
    Обновляет Гугл Таблицу для переданного Мода.
    """
    insert_row = 3

    task_ids_and_values = (
        GSpreadTask
        .select(
            GSpreadTask.id,
            GSpreadTask.values_to_upload,
        )
        .where(
            GSpreadTask.uploaded.is_null(),
            GSpreadTask.retry_count < cfg.UPLOAD_GOOGLE_MAX_ATTEMPTS,
        )
        .join(Task)
        .where(
            Task.report == report,
        )
        .order_by(GSpreadTask.id.asc())
    )


    # Количество успешно загруженных строк.
    uploaded_count = 0

    for chunk_start in range(0, len(task_ids_and_values), chunk_size):
        tasks_chunk = task_ids_and_values[chunk_start:chunk_start + chunk_size]

        # Набор строк со значениями ячеек.
        rows = []
        for chunk_item in tasks_chunk:
            row = prepare_row(chunk_item.values_to_upload)
            rows.append(row)
        reversed_rows = list(reversed(rows))

        attempt_time = datetime.now()
        uploaded_date = None

        try:
            # Выгрузка строк в Гугл Таблицу.
            api = SheetsApi(report.sheet_id)
            # Выгрузка в новые строки.
            api.insert_rows(reversed_rows, insert_row)
        except Exception as ex:
            logger.error(f'Ошибка при выгрузке в Гугл Таблицу Отчет {report.id}: {ex}')
        else:
            uploaded_date = attempt_time
            uploaded_count += len(rows)

        # Обновляем статусы задач.
        task_ids = [x.id for x in task_ids_and_values]
        chunk_tasks = GSpreadTask.select().where(GSpreadTask.id.in_(task_ids))
        for t in chunk_tasks:
            t.retry_count += 1
            t.last_attempt = attempt_time
            # Если задача успешно выполнена.
            if uploaded_date is not None:
                t.uploaded = uploaded_date

        # Обновляем в БД только те поля, которые действительно изменили.
        update_fields = [GSpreadTask.retry_count, GSpreadTask.last_attempt]
        if uploaded_date is not None:
            update_fields.append(GSpreadTask.uploaded)

        GSpreadTask.bulk_update(chunk_tasks, fields=update_fields, batch_size=500)

    if uploaded_count > 0:
        logger.info(f'[+] Успешно выгружено {uploaded_count} строк в Таблицу {report.sheet_id}.')
    else:
        logger.info(f'[-] Ничего не выгружено в Таблицу {report.sheet_id} (0 строк).')


def upload_tasks_in_threads():
    """
    Запускает многопоточную выгрузку строк в Гугл Таблицы.
    Каждый поток обрабатывает Гугл Таблицу одного отчета.
    """

    # Отчеты, для которых нужно сделать выгрузку в Гугл Таблицу.
    reports = (
        Report
        .select(Report.id, Report.sheet_id)
        .where(
            Report.sheet_id.is_null(False),
            Report.sheet_id != 'null',
        )
        .join(Task, on=(Task.report == Report.id))
        .join(GSpreadTask, on=(GSpreadTask.task == Task.id))
        .where(
            GSpreadTask.uploaded.is_null(),
            GSpreadTask.retry_count < cfg.UPLOAD_GOOGLE_MAX_ATTEMPTS,
        )
        .group_by(Report.id)
    )
    logger.info(f'Начинаю выгружать звонки в Гугл Таблицы: всего отчетов {len(reports)}.')

    with ThreadPoolExecutor(max_workers=cfg.UPLOAD_GOOGLE_MAX_WORKERS) as executor:
        futures = []
        for report in reports:
            futures.append(executor.submit(update_google_report, report, chunk_size=cfg.UPLOAD_GOOGLE_CHUNK_SIZE))
        for future in futures:
            future.result()


def main():
    while True:
        upload_tasks_in_threads()
        logger.info('Ожидание 1 мин перед следующей попыткой...')
        time.sleep(60)


if __name__ == "__main__":
    main()
