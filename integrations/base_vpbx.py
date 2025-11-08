from datetime import datetime, timedelta
from typing import List

from assemblyai import LemurError
from loguru import logger

from data.models import Integration, IntegrationServiceName, VPBXCall, Report
from helpers.db_helpers import not_enough_company_balance, create_task
from misc.time import get_refresh_time
from modules.audio_processor import process_crm_call
from modules.audiofile import Audiofile


class AccessIntegrationError(Exception):
    """
    Ошибка доступа к интегрированной системе.
    """
    pass


class CallDownloadError(Exception):
    """
    Ошибка загрузки звонка из телефонии.
    """
    pass


class BaseVPBXProcessor:
    """
    Универсальный класс для подключения Телефонии.
    Обрабатывает все найденные в БД интеграции указанного типа (service_name).
    """

    def __init__(
            self,
            service_name: IntegrationServiceName,
            lookback_hours: int = 12,
    ):
        """
        lookback_hours: за какое количество предыдущих часов получать записи для обработки.
        """
        self.service_name = service_name
        self.lookback_hours = lookback_hours

    @staticmethod
    def get_api_client(
            integration: Integration,
    ):
        """
        Возвращает API-клиент Телефонии.
        """
        raise NotImplementedError

    def get_calls(
            self,
            report: Report,
            client,
            date_from: datetime,
    ) -> list:
        """
        Возвращает список звонков, начиная с даты date_from.
        """
        raise NotImplementedError

    def get_call_id(self, call) -> str:
        raise NotImplementedError

    def get_call_date(self, call) -> datetime:
        raise NotImplementedError

    def get_call_duration(self, call) -> int:
        raise NotImplementedError

    def get_call_responsible_user(self, call) -> str:
        """
        Возвращает человекочитаемое имя ответственного.
        """
        raise NotImplementedError

    def get_call_direction(self, call) -> str:
        """
        Возвращает человекочитаемое название направления звонка.
        """
        raise NotImplementedError

    def filter_new_calls(
            self,
            report: Report,
            calls: list,
            chunk_size: int = 5000,
    ) -> list:
        """
        Выбирает из списка звонков те, которые еще не обрабатывались.
        """
        # Список ID всех звонков.
        incoming_call_ids = [self.get_call_id(call) for call in calls]

        # Уже обработанные call_id переданной интеграции.
        existing_call_ids = set()

        # Обращаемся к БД партиями размером до chunk_size.
        for i in range(0, len(incoming_call_ids), chunk_size):
            call_ids_chunk = incoming_call_ids[i:i + chunk_size]

            query = VPBXCall.select(VPBXCall.call_id).where(
                VPBXCall.integration == report.integration,
                VPBXCall.call_id.in_(call_ids_chunk),
            )
            existing_call_ids.update(row.call_id for row in query)

        logger.info(f"[-] {self.service_name} Отчет {report.id} – "
                    f"Записей, которые уже обрабатывались: {len(existing_call_ids)}. Пропускаем. "
                    f"Список call_id: {existing_call_ids}.")

        # Новые звонки.
        new_calls = [call for call in calls
                     if self.get_call_id(call) not in existing_call_ids]
        return new_calls

    def check_duration_filters(
            self,
            call,
            filters: dict,
    ):
        """
        Проверка фильтров:
        1. Ненулевой длительности звонка.
        2. Минимальной длительности звонка.
        3. Максимальной длительности звонка.
        """
        call_duration_sec = self.get_call_duration(call)

        # 1. Проверка ненулевой длительности звонка.
        if call_duration_sec == 0:
            logger.info(f'[-] {self.service_name} – Звонок не состоялся. Duration: 0')
            return False

        # 2. Проверка минимальной длительности звонка.
        min_duration = filters.get('min_duration')
        if min_duration and call_duration_sec < min_duration:
            logger.info(
                f'[-] {self.service_name} – Не проходим по мин. длительности. Факт. длит.: {call_duration_sec}, мин: {min_duration}')
            return False

        # 3. Проверка максимальной длительности звонка.
        max_duration = filters.get('max_duration')
        if max_duration and call_duration_sec > max_duration:
            logger.info(
                f'[-] {self.service_name} – Не проходим по макс. длительности. Факт. длит.: {call_duration_sec}, макс: {max_duration}')
            return False

        return True

    def check_custom_filters(
            self,
            call,
            filters: dict,
    ):
        raise NotImplementedError

    def check_call_filters(
            self,
            call,
            filters: dict,
    ) -> bool:
        """
        Проверка фильтров.
        True – проверка всех фильтров пройдена успешно.
        False – проверка неуспешна, то есть хотя бы один из фильтров не был пройден.
        """
        if not self.check_duration_filters(call, filters):
            return False
        if not self.check_custom_filters(call, filters):
            return False
        return True

    def get_record_url(
            self,
            client,
            call,
    ) -> str:
        """
        Возвращает URL для скачивания аудиофайла для переданного звонка.
        """
        raise NotImplementedError

    @staticmethod
    def get_download_headers(client) -> dict:
        return {}

    def make_crm_values_to_upload(
            self,
            call,
    ) -> List[dict]:
        """
        Создание ячеек для Google таблицы:
        1. Дата и время обработки звонка.
        2. Дата и время звонка.
        3. Продолжительность звонка (в секундах).
        4. Фамилия ответственного (и имя, если есть).
        5. Направление вызова (входящий, исходящий).
        """
        refresh_time = get_refresh_time()
        call_date = self.get_call_date(call).strftime('%Y-%m-%d %H:%M')
        duration_sec = self.get_call_duration(call)
        responsible_user_name = self.get_call_responsible_user(call)
        direction = self.get_call_direction(call)

        basic_data_full = [
            {'crm_id': 'refresh_time', 'value': refresh_time},
            {'crm_id': 'call_date', 'value': call_date},
            {'crm_id': 'duration_min_sec', 'value': duration_sec},
            {'crm_id': 'responsible_user_name', 'value': responsible_user_name},
            {'crm_id': 'direction', 'value': direction},
        ]

        return basic_data_full

    def download_call(self, client, call, call_id: str) -> Audiofile:
        try:
            call_url = self.get_record_url(client, call)
        except ValueError:
            raise CallDownloadError

        audio = Audiofile().load_from_url(call_url,
                                          name=f'{self.service_name}_{call_id}',
                                          headers=self.get_download_headers(client))
        return audio

    def process_call(
            self,
            report: Report,
            client,
            call,
    ):
        """
        Обрабатывает единичный звонок.
        """
        call_id = self.get_call_id(call)
        logger.info(f"{self.service_name} Отчет {report.id}. "
                    f"Обрабатываем звонок: {call_id}.")

        VPBXCall.create(
            integration=report.integration,
            call_id=call_id,
            call_created=self.get_call_date(call),
        )

        logger.info('Проверяем фильтры.')
        filters = report.get_report_filters()
        if not self.check_call_filters(call, filters):
            return None

        logger.info('Загружаем звонок.')
        try:
            audio = self.download_call(client, call, call_id)
        except CallDownloadError:
            return None

        logger.info('Проверяем баланс.')
        company = report.integration.company

        # Проверка баланса по фактической длине аудиозаписи.
        if not_enough_company_balance(company, audio.duration_in_sec):
            return None

        logger.info('Повторно проверяем длительность звонка.')
        min_duration = filters.get('min_duration')
        max_duration = filters.get('max_duration')
        if (
                min_duration and audio.duration_in_sec < min_duration
                or max_duration and audio.duration_in_sec > max_duration
        ):
            logger.info(f'[-] {self.service_name} Отчет {report.id} – Не проходим по реальной длительности. '
                        f'Факт. длит.: {audio.duration_in_sec}, фильтр: {min_duration}-{max_duration}')
            return None

        task = create_task(audio.duration_in_sec,
                           audio.url,
                           report,
                           initial_duration=self.get_call_duration(call))
        logger.info(f'Создал новый {self.service_name} Task {task.id} для отчета {report.id}.')

        logger.info('Получаем basic_data')
        crm_values_to_upload = self.make_crm_values_to_upload(call)

        logger.info('Анализ аудиозаписи и выгрузка отчета.')
        process_crm_call(audio, company, crm_values_to_upload, task)

        logger.info('Звонок успешно обработан.')
        return None

    def process_report(
            self,
            report: Report,
            date_from: datetime,
    ) -> int:
        """
        Обрабатывает все звонки переданного отчета.
        Возвращает количество обработанных звонков.
        """
        assert report.integration.service_name == self.service_name
        logger.info(f'Обрабатываем отчет {report.name} (id={report.id}).')

        client = self.get_api_client(report.integration)
        try:
            calls = self.get_calls(report, client, date_from)
        except AccessIntegrationError:
            report.active = False
            report.save(only=['active'])
            raise

        logger.info(f'Всего получено {len(calls)} звонков.')

        new_calls = self.filter_new_calls(report, calls)
        logger.info(f'Новых звонков для обработки: {len(new_calls)}.')

        for call in new_calls:
            try:
                self.process_call(report, client, call)
            except LemurError as ex:
                logger.error(ex)
                continue
        new_processed_count = len(new_calls)

        return new_processed_count

    def process(
            self,
    ):
        """
        Обрабатывает звонки для всех отчетов, связанных с интеграциями нужной телефонии.
        """
        # Самая ранняя возможная дата звонка.
        date_from = (datetime.now().astimezone().replace(microsecond=0) - timedelta(hours=self.lookback_hours))

        # Отчеты для обработки. Только активные.
        integrations = Integration.select().where(Integration.service_name == self.service_name)
        reports = Report.select().where(Report.integration.in_(integrations),
                                        Report.active == True)

        logger.info(f'{self.service_name} – Запустили обработку. '
                    f'Выбрано {reports.count()} отчётов. '
                    f'Обрабатываем звонки за последние {self.lookback_hours} часов, '
                    f'начиная с {date_from}.')

        for report in reports:
            try:
                new_processed_count = self.process_report(report, date_from)
            except Exception as ex:
                logger.info(f'[-] {self.service_name} Отчет {report.id} – '
                            f'Не удалось обработать звонки. Неизвестная ошибка: {ex}.')
            else:
                logger.info(f'[+] {self.service_name} Отчет {report.id} – '
                            f'Обработали новых звонков: {new_processed_count}.')

        logger.info('Завершили обработку всех отчетов.')
