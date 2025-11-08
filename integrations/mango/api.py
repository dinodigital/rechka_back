import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional, List
from urllib.parse import urljoin

import requests


class MangoClient:

    """
    API-клиент для работы с ВАТС Манго.
    """

    def __init__(
            self,
            api_key: str,
            api_salt: str,
            base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.api_salt = api_salt

        self.base_url = base_url or 'https://app.mango-office.ru/'
        self.default_headers = {
            'Content-type': 'application/x-www-form-urlencoded',
        }

    def generate_sign(
            self,
            str_payload: str,
    ) -> str:
        sign_str = f'{self.api_key}{str_payload}{self.api_salt}'
        sign = sha256(sign_str.encode('utf-8')).hexdigest()
        return sign

    def generate_request_data(
            self,
            json_payload: dict,
    ) -> dict:
        str_payload = json.dumps(json_payload, separators=(',', ':'))
        sign = self.generate_sign(str_payload)
        data = {
            'vpbx_api_key': self.api_key,
            'sign': sign,
            'json': str_payload,
        }
        return data

    def send_stats_request(
            self,
            date_from: datetime,
            limit: int = 10,
            offset: int = 0,
    ) -> str:
        url = urljoin(self.base_url, '/vpbx/stats/calls/request')

        start_date = date_from.strftime('%d.%m.%Y %H:%M:%S')
        end_date = datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S')
        params = {
            'start_date': start_date,
            'end_date': end_date,
            'limit': str(limit),
            'offset': str(offset),
        }
        data = self.generate_request_data(params)

        response = requests.post(url, data=data, headers=self.default_headers)
        stats_key = response.json()['key']
        return stats_key

    def get_stats_result(
            self,
            key: str,
    ):
        url = urljoin(self.base_url, '/vpbx/stats/calls/result/')
        params = {'key': key}
        data = self.generate_request_data(params)

        for _ in range(60):
            response = requests.post(url, data=data, headers=self.default_headers)
            if response.status_code == 200:
                j_resp = response.json()
                if j_resp['result'] == 1000 and j_resp['status'] == 'complete':
                    return j_resp
            time.sleep(1)

        raise Exception('Не удалось получить статистику.')

    def get_call_list(
            self,
            date_from: datetime,
            limit: int = 1000,
    ):
        stats_key = self.send_stats_request(date_from, limit=limit)
        stats = self.get_stats_result(stats_key)
        try:
            calls = stats['data'][0]['list']
        except KeyError:
            return []
        return calls

    def get_record_link(self, recording_id: str) -> str:
        url = urljoin(self.base_url, '/vpbx/queries/recording/post')
        params = {'recording_id': recording_id, 'action': 'download'}
        data = self.generate_request_data(params)

        # В случае успеха идет переадресация по временной прямой ссылке на файл.
        response = requests.post(url, data=data, headers=self.default_headers, allow_redirects=False)
        file_url = response.headers['location']
        return file_url

    def get_balance(self) -> float:
        url = urljoin(self.base_url, '/vpbx/account/balance')
        data = self.generate_request_data({})
        response = requests.post(url, data=data, headers=self.default_headers, allow_redirects=False)
        balance = response.json()['balance']
        return balance

    @staticmethod
    def get_call_recording_ids(call: dict) -> list:
        ids = []
        for cc in call['context_calls']:
            ids.extend(cc['recording_id'])
        return ids

    def get_users(self) -> List[dict]:
        url = urljoin(self.base_url, '/vpbx/config/users/request')
        params = {
            'ext_fields': ['general.user_id']
        }
        data = self.generate_request_data(params)
        response = requests.post(url, data=data, headers=self.default_headers, allow_redirects=False)
        users = response.json()['users']
        return users
