import time
from datetime import datetime

import pytz
from loguru import logger

from config import config
from data.models import Integration, IntegrationServiceName, Report
from integrations.base_vpbx import BaseVPBXProcessor
from integrations.mango.api import MangoClient
from integrations.mango.models import Direction


class MangoProcessor(BaseVPBXProcessor):

    def __init__(
            self,
            *args,
            **kwargs,
    ):
        kwargs['service_name'] = IntegrationServiceName.MANGO
        super().__init__(*args, **kwargs)

    @staticmethod
    def get_api_client(
            integration: Integration,
    ) -> MangoClient:
        api_key = integration.get_decrypted_access_field('api_key')
        api_salt = integration.get_decrypted_access_field('api_salt')
        client = MangoClient(api_key, api_salt)
        return client

    def get_calls(
            self,
            report: Report,
            client: MangoClient,
            date_from: datetime,
    ) -> list:
        try:
            return client.get_call_list(date_from)
        except IndexError:
            return []

    def get_call_id(self, call: dict) -> str:
        return call['entry_id']

    def get_call_date(self, call: dict) -> datetime:
        return datetime.fromtimestamp(call['context_start_time'], tz=pytz.timezone(config.TIME_ZONE))

    def get_call_duration(self, call: dict) -> int:
        return call['talk_duration']

    def get_call_responsible_user(self, call: dict) -> str:
        if call['context_type'] == Direction.INBOUND:
            try:
                members = call['context_calls'][0]['members']
                return members[0]['call_abonent_info']
            except IndexError:
                raise IndexError('Не удалось найти ответственного.')

        elif call['context_type'] == Direction.OUTBOUND:
            return call['caller_name']

        raise ValueError('Неизвестный тип звонка.')

    def get_call_direction(self, call: dict) -> str:
        return Direction.get_rus(call['context_type'])

    def get_record_url(
            self,
            client,
            call,
    ) -> str:
        recording_ids = client.get_call_recording_ids(call)
        logger.debug(f'Найдено записей разговора: {len(recording_ids)}.')
        if len(recording_ids) == 0:
            raise ValueError('Не удалось найти запись звонка')
        call_url = client.get_record_link(recording_ids[0])
        return call_url

    def check_custom_filters(
            self,
            call: dict,
            filters: dict,
    ) -> bool:
        """
        Проверка фильтров:
        1. Ответственных.
        2. Типа звонка (входящий, исходящий).

        True – проверка всех фильтров пройдена успешно.
        False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
        """
        # 1. Проверка ответственных.
        allowed_responsible_users = [str(x).strip() for x in filters.get('responsible_users', [])]
        responsible_user = self.get_call_responsible_user(call)
        if allowed_responsible_users and responsible_user not in allowed_responsible_users:
            logger.info(f'[-] {self.service_name} – Ответственный: {responsible_user}, фильтр: {allowed_responsible_users}')
            return False

        # 2. Проверка типа звонка.
        allowed_call_types = filters.get('allowed_call_types')
        if allowed_call_types and not Direction.is_allowed_by_filters(call['context_type'], allowed_call_types):
            logger.info(f'[-] {self.service_name} – Тип звонка: {call["context_type"]}. Фильтр: {allowed_call_types}')
            return False

        return True


def main():
    processor = MangoProcessor()
    while True:
        processor.process()
        time.sleep(600)


if __name__ == '__main__':
    main()
