import csv
import time
from datetime import datetime
from io import StringIO

from loguru import logger
from requests import HTTPError
from sipuni_api import SipuniException

from data.models import Integration, IntegrationServiceName, Report
from integrations.base_vpbx import BaseVPBXProcessor, AccessIntegrationError, CallDownloadError
from integrations.sipuni.api import SipuniClient
from integrations.sipuni.models import Direction
from modules.audiofile import Audiofile


class SipuniProcessor(BaseVPBXProcessor):

    def __init__(
            self,
            *args,
            **kwargs,
    ):
        kwargs['service_name'] = IntegrationServiceName.SIPUNI
        super().__init__(*args, **kwargs)

    @staticmethod
    def get_api_client(
            integration: Integration,
    ) -> SipuniClient:
        token = integration.get_decrypted_access_field('application_token')
        client = SipuniClient(integration.account_id, token=token)
        return client

    def get_calls(
            self,
            report: Report,
            client: SipuniClient,
            date_from: datetime,
    ) -> list:
        try:
            calls_raw = client.get_call_stats(from_date=date_from, to_date=datetime.now())
        except SipuniException:
            raise AccessIntegrationError

        csv_file = StringIO(calls_raw)
        calls = csv.DictReader(csv_file, delimiter=';')
        calls_list = [x for x in calls]
        return calls_list

    def get_call_id(self, call: dict) -> str:
        return call['ID записи']

    def get_call_date(self, call: dict) -> datetime:
        return datetime.strptime(call['Время'], '%d.%m.%Y %H:%M:%S')

    def get_call_duration(self, call: dict) -> int:
        return int(call['Длительность звонка, сек'] or '0')

    def get_call_responsible_user(self, call: dict) -> str:
        call_type = call.get('\ufeffТип')

        if call_type == Direction.INBOUND:
            responsible_user = call['Куда']
        elif call_type == Direction.OUTBOUND:
            responsible_user = call['Откуда']
        else:
            responsible_user = call['Ответственный из CRM']

        return responsible_user

    def get_call_direction(self, call) -> str:
        return Direction.get_rus(call.get('\ufeffТип'))

    def get_record_url(
            self,
            client: SipuniClient,
            call: dict,
    ) -> str:
        pass

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
        responsible_users_not_in = [str(x).strip() for x in filters.get('responsible_users_not_in', [])]

        if allowed_responsible_users or responsible_users_not_in:
            responsible_user = self.get_call_responsible_user(call)

            if allowed_responsible_users and responsible_user not in allowed_responsible_users:
                logger.info(f'[-] {self.service_name} – '
                            f'Ответственный: {responsible_user}, фильтр: responsible_users={allowed_responsible_users}')
                return False

            if responsible_users_not_in and responsible_user in responsible_users_not_in:
                logger.info(f'[-] {self.service_name} – '
                            f'Ответственный: {responsible_user}, фильтр: {responsible_users_not_in=}')
                return False

        # 2. Проверка направления звонка.
        call_direction = call.get("\ufeffТип")
        allowed_call_types = filters.get('allowed_call_types')
        if allowed_call_types and not Direction.is_allowed_by_filters(call_direction, allowed_call_types):
            logger.info(f'[-] {self.service_name} – Тип звонка: {call_direction}. Фильтр: {allowed_call_types}')
            return False

        return True

    def download_call(
            self,
            client: SipuniClient,
            call: dict,
            call_id: str,
    ) -> Audiofile:
        try:
            call_id = self.get_call_id(call)
            record = client.get_record(call_id)
        except SipuniException:
            raise CallDownloadError

        record_content = record.get('content')

        try:
            decoded_record = record_content.decode('utf-8')
        except UnicodeDecodeError:
            decoded_record = ''

        if decoded_record == 'Record was not found':
            logger.info(f'[-] {self.service_name} – Запись не найдена: {call_id}')
            raise CallDownloadError

        elif decoded_record == 'Call not found':
            logger.info(f'[-] {self.service_name} – Звонок не найден: {call_id}')
            raise CallDownloadError

        try:
            audio = Audiofile().load_from_sipuni(record_content, record.get('headers'))
        except HTTPError:
            logger.info(f'[-] {self.service_name} – Не удалось скачать аудиофайл: {call_id}')
            raise CallDownloadError

        return audio


def main():
    processor = SipuniProcessor()
    while True:
        processor.process()
        time.sleep(600)


if __name__ == '__main__':
    main()
