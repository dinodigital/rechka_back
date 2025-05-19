from typing import Optional

from misc.time import get_refresh_time


def generate_prompt(data, extra_data: Optional[dict] = None) -> str:
    """
    extra_data – это словарь, значения которого нужно добавить в общий контекст промпта.
    """
    if extra_data is None:
        extra_data = {}

    # Извлекаем контекст и вопросы
    context = data['context']
    context += f' Сейчас: {get_refresh_time()}. '
    if extra_data:
        context += 'Данные из CRM системы по этому звонку: \n'
        for name, value in extra_data.items():
            context += f'{name}: {value}\n'
        context += '\n'

    questions = data['questions']

    # Формируем промпт
    prompt = f"""
Проанализируй разговор и ответь на следующие вопросы. Твой ответ должен быть в формате JSON, содержащий только список объектов с ключами 'number', 'question' и 'answer' для каждого вопроса. Не добавляй никаких дополнительных комментариев или пояснений.

Общий контекст разговора: {context}

Вот вопросы:
"""

    for index, question in enumerate(questions, start=1):
        q_text = question['question']
        q_context = question.get('context', '')
        q_format = question.get('answer_format', '')
        q_options = question.get('answer_options', '')

        prompt += f"{index}. {q_text}\n"
        if q_context:
            prompt += f"   Контекст: {q_context}\n"
        if q_format:
            prompt += f"   Формат ответа: {q_format}\n"
        if q_options:
            prompt += f"   Варианты ответа: {', '.join(q_options)}\n"
        prompt += "\n"

    prompt += """
Ответь только в следующем формате JSON, без дополнительных комментариев:

[
    {
        "number": 1,
        "question": "Вопрос 1",
        "answer": "Ответ 1"
    },
    {
        "number": 2,
        "question": "Вопрос 2",
        "answer": "Ответ 2"
    },
    ...
]
"""

    return prompt
