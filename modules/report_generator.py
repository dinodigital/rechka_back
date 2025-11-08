import os
from typing import Optional, List, Tuple

from assemblyai import Transcript
from loguru import logger

from config import config


class ReportGenerator:

    """
    Создает текстовые отчеты о звонке (анализ и/или транскрибация).
    """

    def __init__(
            self,
            transcript: Optional[Transcript] = None,
    ):
        self.transcript = transcript

    @staticmethod
    def generate_string_report(sorted_analyze_data: List[Tuple[str]]) -> str:
        logger.info("Создаю отчет о звонке")

        string_report = ""
        for short_name, answer_text in sorted_analyze_data:
            string_report += (f"{short_name}\n"
                              f"-----------------------\n"
                              f"{answer_text}\n"
                              f"\n")

        return string_report

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

    def generate_txt_report(self, sorted_analyze_data: Optional[List[Tuple[str]]] = None) -> str:
        """
        Создает отчет о звонке с анализом и транскрибацией.
        Записывает результат в файл. Имя файла генерируется на основе transcript.id.
        """
        logger.info("Создаю отчет звонка")

        txt_report = ''
        if sorted_analyze_data:
            txt_report += self.generate_string_report(sorted_analyze_data)
        txt_report += self.generate_transcript(add_header=True)

        # Запись диалога в файл
        path = os.path.join(config.DOWNLOADS_PATH, f"transcript_{self.transcript.id}.txt")

        with open(path, mode="w", encoding="utf-8") as f:
            f.write(txt_report)

        absolute_path = os.path.abspath(path)
        return absolute_path
