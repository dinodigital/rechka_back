def get_number_from_integration_settings(settings: dict):
    if settings:
        entity_deal_number = settings.get("entity_deal_number")
        if entity_deal_number is None:
            number = 0
        elif entity_deal_number == "first":
            number = 0
        elif entity_deal_number == "last":
            number = -1
        elif isinstance(entity_deal_number, int):
            number = entity_deal_number
        else:
            number = 0
    else:
        number = 0

    return number
