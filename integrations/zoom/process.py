import time
from datetime import datetime

from loguru import logger
from zoomus import ZoomClient

from data.models import IntegrationServiceName, Integration, Report
from integrations.base_vpbx import BaseVPBXProcessor


class ZoomProcessor(BaseVPBXProcessor):

    def __init__(
            self,
            *args,
            **kwargs,
    ):
        kwargs['service_name'] = IntegrationServiceName.ZOOM
        super().__init__(*args, **kwargs)

    @staticmethod
    def get_api_client(
            integration: Integration,
    ) -> ZoomClient:

        client_id =     integration.get_decrypted_access_field('client_id')
        client_secret = integration.get_decrypted_access_field('client_secret')
        account_id =    integration.get_decrypted_access_field('account_id')

        client = ZoomClient(client_id, client_secret, account_id)
        return client

    def get_calls(
            self,
            report: Report,
            client: ZoomClient,
            date_from: datetime,
    ) -> list:
        # Почты пользователей, звонки которых нужно обрабатывать.
        responsible_users_in = report.get_report_filters().get('responsible_users', [])
        # Почты пользователей, звонки которых игнорировать.
        skipped_emails = []

        users = []
        all_users = client.user.list().json()['users']

        for user in all_users:
            if user['email'] in responsible_users_in:
                users.append(user)
            else:
                skipped_emails.append(user['email'])

        if skipped_emails:
            logger.info(f'[-] {self.service_name} – Пропускаем звонки пользователей: {skipped_emails}, '
                        f'фильтр responsible_users_in: {responsible_users_in}')

        # Собираем звонки всех нужных пользователей.
        calls = []
        for user in users:
            recordings = client.recording.list(user_id=user['id'], start=date_from)
            meetings = recordings.json().get('meetings', [])

            for call in meetings:

                # Пропускаем встречи, звонки которых еще не загрузились.
                if any(rf.get('status') != 'completed' for rf in call.get('recording_files', [])):
                    logger.debug(f'Звонов с id={self.get_call_id(call)} еще не загрузился. Пропускаем.')
                    continue

                # Добавляем почту ответственного к каждому звонку.
                call['responsible_user'] = user['email']

                calls.append(call)

        return calls

    @staticmethod
    def get_record_from_call(call: dict):
        for m in call['recording_files']:
            if m.get('recording_type') == 'audio_only':
                return m
        raise ValueError('Не удалось найти запись встречи.')

    def get_call_id(self, call) -> str:
        return str(call['id'])

    def get_call_date(self, call) -> datetime:
        return datetime.strptime(call['start_time'], '%Y-%m-%dT%H:%M:%SZ')

    def get_call_duration(self, call) -> int:
        record = self.get_record_from_call(call)
        start_time = datetime.strptime(record['recording_start'], '%Y-%m-%dT%H:%M:%SZ')
        end_time = datetime.strptime(record['recording_end'], '%Y-%m-%dT%H:%M:%SZ')
        duration = int((end_time - start_time).total_seconds())
        return duration

    def get_call_responsible_user(self, call) -> str:
        return call['responsible_user']

    def get_call_direction(self, call) -> str:
        return ''

    def get_record_url(
            self,
            client,
            call,
    ) -> str:
        return self.get_record_from_call(call)['download_url']

    @staticmethod
    def get_download_headers(client) -> dict:
        return {'Authorization': f'Bearer {client.config["token"]}'}

    def check_custom_filters(
            self,
            call: dict,
            filters: dict,
    ) -> bool:
        """
        Проверка фильтров:
        1. Ответственных.

        True – проверка всех фильтров пройдена успешно.
        False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
        """

        # 1. Проверка ответственных.
        # Пропускаем, так как изначально обрабатываются звонки только нужных пользователей (из списка responsible_users).
        pass

        return True


def main():
    processor = ZoomProcessor()
    while True:
        processor.process()
        time.sleep(600)


if __name__ == '__main__':
    main()
