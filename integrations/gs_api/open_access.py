import gspread

from config.config import GOOGLE_PATH


def open_spreadsheet(spreadsheet_id):
    gc = gspread.service_account(filename=GOOGLE_PATH)

    # Открытие таблицы по ID
    spreadsheet = gc.open_by_key(spreadsheet_id)

    # Открытие доступа к таблице всем
    spreadsheet.share(None, perm_type='anyone', role='writer')

    print(f"Доступ к таблице с ID {spreadsheet_id} открыт для всех.")


