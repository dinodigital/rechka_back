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
from modules.prompt_generator import generate_prompt


aai.settings.api_key = ASSEMBLYAI_KEY


class Assembly:

    def __init__(self, lemur_params):
        self.aai = aai
        self.aai.settings.api_key = ASSEMBLYAI_KEY
        self.lemur_params: dict = lemur_params
        self.transcript: Transcript | None = None
        self.lemur_response: LemurQuestionResponse | LemurTaskResponse | None = None
        self.analyze_list: List | None = None

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
    def transcribe_audio(self, file_url: str, speaker_labels: bool = True,
                         speakers_expected: bool = None) -> Transcript:
        """
        Транскрибация аудиофайла
        """
        logger.info("AssemblyAi → Транскрибирую аудиозапись")

        config = aai.TranscriptionConfig(
            punctuate=True,  # Пунктуация
            format_text=True,  # Форматирование текста
            language_code="ru",  # Выбор языка
            speaker_labels=speaker_labels,  # Разделение по собеседникам (A, B, C, D, ... )
            speakers_expected=speakers_expected  # Ожидаемое количество собеседников
        )
        transcriber: Transcriber = self.aai.Transcriber(config=config)
        transcript: Transcript = transcriber.transcribe(file_url)

        return transcript

    @retry(tries=3, delay=1, backoff=2)
    def ask_lemur(self, transcript: Transcript, params: dict) -> LemurQuestionResponse:
        """
        Ответы на вопросы с помощью LeMUR
        """
        logger.info("AssemblyAi → Анализирую транскрипт через QUESTIONS")
        return transcript.lemur.question(**params)

    @staticmethod
    def task(
            transcript: Transcript,
            prompt: str,
            final_model: LemurModel | None = aai.LemurModel.claude3_5_sonnet,
            temperature: float | None = None
    ) -> LemurTaskResponse:
        """
        Единый ответ на вопросы с помощью LeMUR с учетом финального модели
        """
        logger.info("AssemblyAi → Анализирую транскрипт через TASK")
        return transcript.lemur.task(
            prompt=prompt,
            final_model=final_model,
            max_output_size=4000,
            temperature=temperature
        )

    @staticmethod
    def smart_lemur_parser(result: LemurQuestionResponse) -> List:
        """
        Умный парсер ответа от LeMUR
        Генерирует список из ответов с учетом shor_name
        """
        out_list = []

        for item in result.response:
            answer = item.answer

            if ";;" in answer:
                out_list += answer.split(";;")
            else:
                try:
                    answer = json.loads(answer)
                    out_list += answer
                except Exception:
                    out_list.append(answer)

        return out_list

    def analyze_audio(self, audio: Audiofile, task: Task) -> 'Assembly':
        """
        Анализирует аудиофайл по пути
        """
        self.transcript = self.transcribe_audio(audio.path)
        update_task_after_transcript(task=task,
                                     assembly_duration=self.transcript.audio_duration,
                                     transcript_id=self.transcript.id)
        self.lemur_response = self.ask_lemur(self.transcript, self.lemur_params)
        update_task_lemur_response(task=task, lemur_response=self.lemur_response)
        self.analyze_list = self.smart_lemur_parser(self.lemur_response)
        update_task_analyze_data(task=task, analyze_data=json.dumps(self.analyze_list))

        return self

    @staticmethod
    def prepare_lemur_response_for_sheet(lemur_response: LemurTaskResponse,
                                         original_questions: List[Dict]) -> List[List[str]]:
        """
        Преобразует ответ LeMUR в список списков для загрузки в Google таблицу.

        :param lemur_response: Ответ от LeMUR
        :param original_questions: Исходный список вопросов с их short_name
        :return: Список списков для загрузки в Google таблицу
        """
        # Преобразуем ответ LeMUR в словарь для удобного доступа
        response_dict = {item['question']: item['answer'] for item in json.loads(lemur_response.response)}

        # Подготавливаем данные для таблицы
        sheet_data = []
        for question in original_questions:
            full_question = question['question']
            answer = response_dict.get(full_question, 'Ответ не найден')
            sheet_data.append(answer)

        return sheet_data

    def analyze_transcript(self, transcript_id: str) -> 'Assembly':
        """
        Анализирует аудиофайл по пути
        """
        self.transcript = self.get_transcript_by_id(transcript_id)
        self.lemur_response = self.ask_lemur(self.transcript, self.lemur_params)
        self.analyze_list = self.smart_lemur_parser(self.lemur_response)

        return self

    def analyze_transcript_with_task(self, transcript_id: str, prompt: str, task: Task,
                                     temperature: float | None = None) -> 'Assembly':
        """
        Анализирует аудиофайл с помощью LeMUR с учетом финального модели
        """
        self.transcript = self.get_transcript_by_id(transcript_id)
        self.lemur_response: LemurTaskResponse = self.task(self.transcript, prompt=prompt, temperature=temperature)
        update_task_lemur_response(task=task, lemur_response=self.lemur_response)
        self.analyze_list = self.prepare_lemur_response_for_sheet(self.lemur_response, self.lemur_params['questions'])
        update_task_analyze_data(task=task, analyze_data=json.dumps(self.analyze_list))

        return self

    def analyze_audio_with_task(self, audio: Audiofile, task: Task, temperature: float | None = None, prompt_extra: Optional[dict] = None) -> 'Assembly':
        """
        Анализирует аудиофайл с помощью LeMUR через TASK (единый ответ)
        """
        self.transcript = self.transcribe_audio(audio.path)
        update_task_after_transcript(task=task,
                                     assembly_duration=self.transcript.audio_duration,
                                     transcript_id=self.transcript.id)
        prompt = generate_prompt(self.lemur_params, extra_data=prompt_extra)

        return self.analyze_transcript_with_task(
            transcript_id=self.transcript.id,
            prompt=prompt,
            task=task,
            temperature=temperature
        )
