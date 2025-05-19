import os


def delete_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        print(f"Ошибка: файл '{path}' не найден.")
    except Exception as e:
        print(f"Ошибка при удалении файла '{path}': {e}")
    else:
        print(f"Файл '{path}' успешно удален.")


def delete_files(file_path_list: list):
    """
    Удаляет файлы. На вход принимает список
    """
    for path in file_path_list:
        delete_file(path)
