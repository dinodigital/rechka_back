from loguru import logger

from integrations.amo_crm.amo_api_core import AmoApi


class AmoLeadLoader(AmoApi):
    def __init__(self, integration):
        super().__init__(integration)

    @staticmethod
    def create_status_filter_dict(status_values, pipeline_id=402):
        filter_dict = {}
        for index, status_id in enumerate(status_values, start=1):
            filter_dict[f"filter[statuses][{index}][pipeline_id]"] = pipeline_id
            filter_dict[f"filter[statuses][{index}][status_id]"] = str(status_id)
        return filter_dict

    @staticmethod
    def _custom_field_filter(lead, custom_field_id: int, custom_field_enums: list):
        custom_fields = lead['custom_fields_values']
        for cf in custom_fields:
            if cf['field_id'] != custom_field_id:
                continue

            for value in cf['values']:
                if value['enum_id'] in custom_field_enums:
                    return True

        return False

    def get_filtered_leads(self, pipeline_id=None, limit=250, page=1, date_from=None, date_to=None):
        """Получение списка всех лидов

        Как работают фильтры AMOCRM
        https://www.amocrm.ru/developers/content/crm_platform/filters-api#leads-filter
        """
        endpoint = "/api/v4/leads"

        params = {
            'limit': limit,
            'page': page,
            'with': "contacts",
        }

        if pipeline_id:
            params.update(**{"filter[pipeline_id]": pipeline_id})

        if date_from:
            if not date_to:
                date_to = date_from
            params.update(**{
                'filter[created_at][from]': self.date_str_to_number(date_from),
                'filter[created_at][to]': self.date_str_to_number(date_to),
            })

        # Все страницы
        leads = []
        while True:
            logger.info(f"Получаю лиды. Страница - {page}")

            params['page'] = page
            r = self.base_request(endpoint=endpoint, type="get", params=params)
            if not r:
                return leads

            leads += r["_embedded"]['leads']
            if r['_links'].get("next") is None:
                logger.info(f"Собрал {len(leads)} лидов")
                return leads

            page += 1

    def get_all_filtered_leads(self, date_from, date_to=None, pipeline_id=None, limit=250, status_in=None,
                               status_not_in=None, custom_field_filters=None):
        """
        ОСНОВНАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ЛИДОВ из AMOCRM

        :param date_from: str '2023-01-01'
        :param date_to: str '2023-01-01'
        :param pipeline_id: int,str array '123123' / '123123,888999'
        :param limit: int
        :param status_in: list [142, 143] / Статус сделки в списке
        :param status_not_in: list [142, 143]  / Статус сделки не в списке
        :param custom_field_filters: list of lists [ [field_id, [enums] ] ]
        """
        leads = self.get_filtered_leads(limit=limit, date_from=date_from, date_to=date_to, pipeline_id=pipeline_id)

        c_leads = []
        for lead in leads:
            if custom_field_filters:
                for custom_filter in custom_field_filters:
                    if not self._custom_field_filter(lead, custom_filter[0], [custom_filter[1]]):
                        continue
            if status_in and lead["status_id"] not in status_in:
                continue
            if status_not_in and lead["status_id"] in status_not_in:
                continue
            c_leads += [lead]

        return c_leads
