import os
from typing import Optional

from assemblyai import Transcript
from loguru import logger

from config import config
from data.models import User, Mode
from integrations.gs_api.sheets_helpers import get_shortnames_by_user


class ReportGenerator:

    """
    Создает текстовые отчеты о звонке (анализ и/или транскрибация).
    """

    def __init__(
            self,
            db_user: User,
            transcript: Optional[Transcript] = None,
            analyze_list: Optional[list] = None,
    ):
        self.db_user = db_user
        self.transcript = transcript
        self.analyze_list = analyze_list

    def generate_json_report(self, mode: Mode = None) -> dict:
        logger.info("Создаю json отчет о звонке")
        short_names = get_shortnames_by_user(self.db_user, mode=mode)
        report = {short_names[i]: item
                  for i, item in enumerate(self.analyze_list)}
        return report

    def generate_string_report(self, mode: Mode = None) -> str:
        logger.info("Создаю отчет о звонке")

        json_report = self.generate_json_report(mode=mode)

        report = ""
        for short_name, analyze_item in json_report.items():
            report += (f"{short_name}\n"
                       f"-----------------------\n"
                       f"{analyze_item}\n"
                       f"\n")

        return report

    def generate_transcript(self, transcript: Optional[Transcript] = None, add_header: bool = False) -> str:
        logger.info("Создаю транскрибацию звонка")

        if transcript is None:
            transcript = self.transcript

        if add_header:
            result = (f"---------------------------\n"
                      f"ТРАНСКРИБАЦИЯ РАЗГОВОРА\n"
                      f"ID: {transcript.id}\n"
                      f"---------------------------\n")
        else:
            result = ""

        for utterance in transcript.utterances:
            result += f"- {utterance.text}\n"

        return result

    def generate_txt_report(self, add_analyze_data: bool = True) -> str:
        """
        Создает отчет о звонке с анализом и транскрибацией.
        Записывает результат в файл. Имя файла генерируется на основе transcript.id.
        """
        logger.info("Создаю отчет звонка")

        txt_report = ''
        if add_analyze_data:
            txt_report += self.generate_string_report()
        txt_report += self.generate_transcript(add_header=True)

        # Запись диалога в файл
        path = os.path.join(config.DOWNLOADS_PATH, f"transcript_{self.transcript.id}.txt")

        with open(path, mode="w", encoding="utf-8") as f:
            f.write(txt_report)

        absolute_path = os.path.abspath(path)
        return absolute_path
