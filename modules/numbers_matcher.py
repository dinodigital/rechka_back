import phonenumbers
from phonenumbers import PhoneNumberMatcher


def phone_number_in_list(text, phone_numbers_list, default_region='RU'):
    # Извлечение номера из текста
    numbers_in_text = [x.number for x in PhoneNumberMatcher(text, default_region)]
    if not numbers_in_text:
        return False  # В тексте не найден номер

    # Нормализация номера из текста
    number_from_text = phonenumbers.format_number(numbers_in_text[0], phonenumbers.PhoneNumberFormat.E164)

    # Нормализация и сравнение номеров из списка
    for raw_number in phone_numbers_list:
        try:
            parsed_number = phonenumbers.parse(raw_number, default_region)
            formatted_number = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
            if formatted_number == number_from_text:
                return True  # Найдено совпадение
        except phonenumbers.NumberParseException:
            continue  # Пропускаем невалидные номера

    return False  # Совпадений не найдено


if __name__ == '__main__':
    phone_number = "8-978-8252577"
    possible_phone_numbers = [
        "+7 978 825-25-77",
        "+7 978 713-33-50",
        "+7 978 707-95-69",
        "+7 978 712-44-91",
        "+7 978 712-39-49",
        "+7 978 097-20-96",
        "+7 978 724-58-53",
        "+7 978 712-44-53",
        "+7 978 731-80-26",
        "+7 978 764-61-60",
        "+7 978 210-05-29",
        "+7 978 020-45-75",
        "+7 978 890-00-37",
        "+7 978 687-84-08",
        "+7 978 040-04-39"
      ]
    print(phone_number_in_list(phone_number, possible_phone_numbers))
