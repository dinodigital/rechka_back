from json import JSONDecodeError

import requests
from sipuni_api import Sipuni, SipuniException


class SipuniClient(Sipuni):

    def _send_api_request(self, method: str, url: str, data: dict = None,
                          headers: dict = None, csv=False, file=False) -> any:
        """
        :param method: str (get, post, put, delete, head)
        :param url: str
        :param data: dict
        :param headers: dict
        :param csv: bool (True in statistic)
        :param file: bool (True in record)
        :return: any
        """
        if data is None:
            data = {}
        if headers is None:
            headers = {}

        self._session.headers.update(headers)
        try:
            response = self._session.__getattribute__(method)(url=url, json=data)
            if response.status_code > 204:
                raise SipuniException(response.status_code, response.reason, response.text)

            if csv:
                return response.content.decode('utf-8')
            elif file:
                return dict(content=response.content, headers=response.headers)
            else:
                return response.json()

        except (requests.ConnectionError, JSONDecodeError):
            raise SipuniException(500,
                                  'Server not answer or Cant decoded to json',
                                  'Server not answer or Cant decoded to json'
                                  )
