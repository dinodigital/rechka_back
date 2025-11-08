import json
from typing import List, Dict, Optional

import assemblyai as aai
from assemblyai import Transcriber, Transcript, LemurQuestionResponse, LemurTaskResponse, LemurModel, TranscriptGroup

from loguru import logger
from retry import retry

from config.config import ASSEMBLYAI_KEY
from data.models import Task
from helpers.db_helpers import update_task_after_transcript, update_task_lemur_response, update_task_analyze_data
from modules.audiofile import Audiofile
from modules.exceptions import LemurParseError
from modules.prompt_generator import generate_prompt


aai.settings.api_key = ASSEMBLYAI_KEY


class Assembly:

    def __init__(
            self,
            context: str,
            final_model: Optional[LemurModel] = LemurModel.claude_sonnet_4_20250514,
    ):
        self.aai = aai
        self.aai.settings.api_key = ASSEMBLYAI_KEY
        self.context = context
        self.final_model = final_model
        self.transcript: Transcript | None = None
        self.lemur_response: LemurQuestionResponse | LemurTaskResponse | None = None
        self.analyze_dict: Dict | None = None

    @retry(tries=3, delay=1, backoff=2)
    def get_transcript_by_id(self, transcript_id: str) -> Transcript:
        """
        Получить транскрипт по id
        """
        logger.info(f"Запрашиваю Транскрипт с id: {transcript_id}")
        return self.aai.Transcript.get_by_id(transcript_id=transcript_id)

    @retry(tries=3, delay=1, backoff=2)
    def get_transcript_list_by_ids(self, transcript_ids: List[str]) -> TranscriptGroup:
        """
        Получить транскрипты по списку ID.
        """
        logger.info(f"Запрашиваю Транскрипты ({len(transcript_ids)} шт.).")
        return self.aai.TranscriptGroup.get_by_ids(transcript_ids)

    @retry(tries=3, delay=1, backoff=2)
    def transcribe_audio(
            self,
            file_url: str,
            speaker_labels: Optional[bool] = True,
            multichannel: Optional[bool] = None,
    ) -> Transcript:
        """
        Транскрибация аудиофайла
        """
        logger.info(f"AssemblyAi → Транскрибирую аудиозапись {speaker_labels=} {multichannel=}")

        config = aai.TranscriptionConfig(
            punctuate=True,  # Пунктуация
            format_text=True,  # Форматирование текста
            multichannel=multichannel, # Распознавание по нескольким каналам аудио.
            language_code="ru",  # Выбор языка
            speaker_labels=speaker_labels,  # Разделение по собеседникам (A, B, C, D, ... )
        )
        transcriber: Transcriber = self.aai.Transcriber(config=config)
        transcript: Transcript = transcriber.transcribe(file_url)

        return transcript

    @staticmethod
    def task(
            transcript: Transcript,
            prompt: str,
            final_model: LemurModel,
            temperature: float | None = None,
            max_output_size: int = 4000,
    ) -> LemurTaskResponse:
        """
        Единый ответ на вопросы с помощью LeMUR с учетом финального модели
        """
        logger.info("AssemblyAi → Анализирую транскрипт через TASK")
        return transcript.lemur.task(
            prompt=prompt,
            final_model=final_model,
            max_output_size=max_output_size,
            temperature=temperature
        )

    @staticmethod
    def parse_lemur_response(response: str):
        response = response.strip('"`')
        if response.startswith('json'):
            response = response[len('json'):]
        return json.loads(response)

    def prepare_lemur_response_for_sheet(
            self,
            lemur_response: LemurTaskResponse,
            mode_questions,
    ) -> dict:
        """
        Преобразует ответ LeMUR в список списков для загрузки в Google таблицу.

        :param lemur_response: Ответ от LeMUR
        :param mode_questions: Список вопросов, на которые нейронная сеть должна была ответить.
        :return: Список списков для загрузки в Google таблицу
        """
        # Преобразуем ответ LeMUR в словарь для удобного доступа:
        # {ID_вопроса: "ответ нейронки", ID_вопроса: "ответ нейронки"}
        response_dict = self.parse_lemur_response(lemur_response.response)
        response_dict = {int(k): v for k, v in response_dict.items()}

        mode_question_ids = {x.id for x in mode_questions}

        # Результат парсинга ответа от нейронной сети.
        sheet_data = {}

        # Сохраняем ответы на вопросы.
        for question_id, answer_text in response_dict.items():
            if question_id in mode_question_ids:
                sheet_data[question_id] = answer_text
            else:
                logger.warning(f'При парсинге ответа от нейронной сети найден неизвестный вопрос ID={question_id}.')

        # Устанавливаем ответы для вопросов, на которые не нашли ответ.
        for question_id in mode_question_ids:
            if question_id not in sheet_data:
                sheet_data[question_id] = 'Ответ не найден'
                logger.warning(f'При парсинге ответа от нейронной сети не найден вопрос ID={question_id}.')

        return sheet_data

    def analyze_transcript_with_task(
            self,
            prompt: str,
            task: Task,
            mode_questions,
            temperature: float | None = None,
    ) -> 'Assembly':
        """
        Анализирует аудиофайл с помощью LeMUR с учетом финального модели
        """
        self.lemur_response: LemurTaskResponse = self.task(self.transcript, prompt, self.final_model, temperature=temperature)
        update_task_lemur_response(task=task, lemur_response=self.lemur_response)
        try:
            self.analyze_dict = self.prepare_lemur_response_for_sheet(self.lemur_response, mode_questions)
        except json.JSONDecodeError:
            raise LemurParseError(self.lemur_response.response, 'Не удалось распарсить ответ от AssemblyAI.')

        update_task_analyze_data(task, self.analyze_dict, mode_questions)

        return self

    def analyze_audio_with_task(
            self,
            audio: Audiofile,
            task: Task,
            mode_questions,
            temperature: Optional[float] = None,
            prompt_extra: Optional[dict] = None,
    ) -> 'Assembly':
        """
        Анализирует аудиофайл с помощью LeMUR через TASK (единый ответ)
        """
        if task.transcript_id is None:
            if audio.channels > 1:
                speaker_labels, multichannel = None, True
            else:
                speaker_labels, multichannel = True, None
            self.transcript = self.transcribe_audio(audio.path, speaker_labels=speaker_labels, multichannel=multichannel)
            update_task_after_transcript(task, self.transcript.audio_duration, self.transcript.id)
        else:
            self.transcript = self.get_transcript_by_id(task.transcript_id)
        prompt = generate_prompt(self.context, mode_questions, extra_data=prompt_extra)

        return self.analyze_transcript_with_task(
            prompt,
            task,
            mode_questions,
            temperature=temperature,
        )
