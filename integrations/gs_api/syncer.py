import gspread
from gspread import Cell
from gspread.utils import ValueInputOption
from loguru import logger

from config.config import LEAD_SHEET_ID, GOOGLE_PATH

gc = gspread.service_account(filename=GOOGLE_PATH)
file = gc.open_by_key(LEAD_SHEET_ID)
worksheet = file.sheet1


# Функция для обновления таблицы
def sync_leads_to_sheet(users, users_info):
    # Получаем все записи из Google Таблицы
    records = worksheet.get_all_records()

    # Маппинг tg_id к индексу строки в Google Таблице
    record_mapping = {record['tg_id']: i + 2 for i, record in enumerate(records)}

    # Ячейки для обновления
    cells_to_update = []

    # Данные для новых строк
    new_rows = []

    for user in users:
        username = users_info[user.tg_id]['username']
        tg_link = f"https://t.me/{username}" if username else ""
        user_data = [user.created.strftime("%d.%m.%Y"),
                     str(user.tg_id),
                     users_info[user.tg_id]['full_name'],
                     str(user.seconds_balance),
                     tg_link]

        if user.tg_id in record_mapping:
            # Рассчитываем индекс строки и добавляем данные для обновления
            row_index = record_mapping[user.tg_id]
            for col_index, value in enumerate(user_data, start=1):
                cells_to_update.append(Cell(row=row_index, col=col_index, value=value))
        else:
            # Добавляем данные для новой строки
            new_rows.append(user_data)

    updated = 0
    added = 0

    # Обновляем существующие ячейки
    if cells_to_update:
        worksheet.update_cells(cells_to_update, value_input_option=ValueInputOption.user_entered)
        updated += len(set(cell.row for cell in cells_to_update))
        logger.info(f"Обновлено строк: {updated}")

    # Добавляем новые строки
    if new_rows:
        worksheet.append_rows(new_rows, value_input_option=ValueInputOption.user_entered)
        added += len(new_rows)
        logger.info(f"Добавлено новых строк: {added}")

    return updated, added

