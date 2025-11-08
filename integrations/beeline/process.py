import time
from datetime import datetime

from beeline_portal import BeelinePBX
from beeline_portal.errors import BeelinePBXException
from beeline_portal.models import CallRecord
from loguru import logger

from data.models import Integration, IntegrationServiceName, Report
from integrations.base_vpbx import BaseVPBXProcessor, AccessIntegrationError
from integrations.beeline.models import Direction
from modules.numbers_matcher import phone_number_in_list


class BeelineProcessor(BaseVPBXProcessor):

    def __init__(
            self,
            *args,
            **kwargs,
    ):
        kwargs['service_name'] = IntegrationServiceName.BEELINE
        super().__init__(*args, **kwargs)

    @staticmethod
    def get_api_client(
            integration: Integration,
    ) -> BeelinePBX:
        token = integration.get_decrypted_access_field('token')
        client = BeelinePBX(token)
        return client

    def get_calls(
            self,
            report: Report,
            client: BeelinePBX,
            date_from: datetime,
    ) -> list:
        params = {'dateFrom': date_from.isoformat()}
        try:
            calls = list(client.get_records(params=params))
        except BeelinePBXException:
            raise AccessIntegrationError
        return calls

    def get_call_id(self, call) -> str:
        return call.id_

    def get_call_date(self, call) -> datetime:
        return call.date

    def get_call_duration(self, call) -> int:
        # Билайн отдает длительность звонка в миллисекундах.
        return call.duration // 1000

    def get_call_responsible_user(self, call) -> str:
        if call.abonent.first_name:
            user_name = f'{call.abonent.first_name} {call.abonent.last_name}'
        else:
            user_name = call.abonent.last_name
        return user_name

    def get_call_direction(self, call) -> str:
        return Direction.get_rus(call.direction)

    def get_record_url(
            self,
            client,
            call,
    ) -> str:
        call_id = self.get_call_id(call)
        call_url = client.get_record_link(call_id)['url']
        return call_url

    def check_custom_filters(
            self,
            call: CallRecord,
            filters: dict,
    ) -> bool:
        """
        Проверка фильтров:
        1. Ответственных.
        2. Запрещенных номеров.
        3. Типа звонка (входящий, исходящий).

        True – проверка всех фильтров пройдена успешно.
        False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
        """
        # 1. Проверка ответственных.
        responsible_phones = [str(x) for x in filters.get('responsible_phones', [])]
        if responsible_phones and not phone_number_in_list(call.abonent.phone, responsible_phones):
            logger.info(f'[-] {self.service_name} – Ответственный: {call.abonent.phone}, фильтр: {responsible_phones}')
            return False

        # 2. Проверка на запрет на анализ телефонных номеров.
        restricted_phones = filters.get('restricted_phones')
        if restricted_phones and phone_number_in_list(call.phone, restricted_phones):
            logger.info(f'[-] {self.service_name} – Установлен запрет на анализ телефона {call.phone}')
            return False

        # 3. Проверка типа звонка.
        allowed_call_types = filters.get('allowed_call_types')
        if allowed_call_types and not Direction.is_allowed_by_filters(call.direction, allowed_call_types):
            logger.info(f'[-] {self.service_name} – Тип звонка: {call.direction}. Фильтр: {allowed_call_types}')
            return False

        return True


def main():
    processor = BeelineProcessor()
    while True:
        processor.process()
        time.sleep(600)


if __name__ == '__main__':
    main()
