"""
AI exam generation service using Google Gemini API.
Falls back to mock generator if GEMINI_API_KEY is not set.
"""
import json
import logging
import os

from django.db import transaction

from .models import Exam, Question, Option

logger = logging.getLogger(__name__)


def _build_prompt(
    title: str,
    theme: str,
    difficulty: str,
    question_count: int,
    file_content: str | None,
) -> str:
    difficulty_map = {'EASY': 'лёгкий', 'MEDIUM': 'средний', 'HARD': 'сложный'}
    diff_label = difficulty_map.get(difficulty, 'средний')

    prompt = (
        f"Создай экзамен на русском языке.\n"
        f"Название: {title}\n"
        f"Тема: {theme or title}\n"
        f"Уровень сложности: {diff_label}\n"
        f"Количество вопросов: {question_count}\n\n"
    )

    if file_content and file_content.strip():
        truncated = file_content.strip()[:8000]
        prompt += (
            f"Используй следующий материал как основу для вопросов:\n"
            f"---\n{truncated}\n---\n\n"
        )
    else:
        prompt += (
            "Материал для вопросов не предоставлен. "
            "Придумай вопросы самостоятельно, опираясь на тему и уровень сложности.\n\n"
        )

    prompt += (
        "Верни ТОЛЬКО валидный JSON (без markdown, без ```json):\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "text": "Текст вопроса",\n'
        '      "type": "CHOICE",\n'
        '      "score": 5,\n'
        '      "options": [\n'
        '        {"text": "Вариант A", "is_correct": false},\n'
        '        {"text": "Вариант B", "is_correct": true},\n'
        '        {"text": "Вариант C", "is_correct": false},\n'
        '        {"text": "Вариант D", "is_correct": false}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Правила:\n"
        "- type всегда 'CHOICE'\n"
        "- у каждого вопроса ровно 4 варианта, один правильный (is_correct: true)\n"
        "- score от 1 до 10 в зависимости от сложности вопроса\n"
        "- НЕ добавляй никаких пояснений, только JSON\n"
    )
    return prompt


# FIXED: wrapped in @transaction.atomic — partial exam (with no questions) can no longer persist
@transaction.atomic
def _create_exam_from_data(
    teacher,
    title: str,
    theme: str,
    difficulty: str,
    data: dict,
) -> Exam:
    exam = Exam.objects.create(
        title=title,
        theme=theme or title,
        difficulty=difficulty or Exam.Difficulty.MEDIUM,
        teacher=teacher,
        max_score=100,
    )

    questions_data = data.get('questions', [])
    total_score = 0
    question_objects = []

    for order, q_data in enumerate(questions_data, start=1):
        score = max(1, min(10, int(q_data.get('score', 5))))
        total_score += score
        question_objects.append(Question(
            exam=exam,
            text=q_data.get('text', f'Вопрос {order}'),
            type=q_data.get('type', Question.Type.CHOICE),
            score=score,
            order=order,
        ))

    # FIXED: bulk_create instead of N individual inserts
    created_questions = Question.objects.bulk_create(question_objects)

    option_objects = []
    for question, q_data in zip(created_questions, questions_data):
        for opt_order, opt_data in enumerate(q_data.get('options', []), start=1):
            option_objects.append(Option(
                question=question,
                text=opt_data.get('text', ''),
                is_correct=bool(opt_data.get('is_correct', False)),
                order=opt_order,
            ))

    Option.objects.bulk_create(option_objects)

    exam.max_score = total_score if total_score > 0 else 100
    exam.save(update_fields=['max_score'])

    return exam


def _mock_generate(title: str, theme: str, question_count: int) -> dict:
    """Fallback generator when API key is not set."""
    questions = []
    for i in range(1, question_count + 1):
        questions.append({
            'text': f'[Тест] Вопрос {i} по теме «{theme or title}»',
            'type': 'CHOICE',
            'score': 5,
            'options': [
                {'text': 'Вариант A', 'is_correct': False},
                {'text': 'Вариант B (правильный)', 'is_correct': True},
                {'text': 'Вариант C', 'is_correct': False},
                {'text': 'Вариант D', 'is_correct': False},
            ],
        })
    return {'questions': questions}


def _clean_json_response(raw: str) -> str:
    """Strip markdown fences from model response."""
    raw = raw.strip()
    if raw.startswith('```'):
        lines = raw.split('\n')
        lines = lines[1:]
        raw = '\n'.join(lines)
    if raw.endswith('```'):
        raw = raw[:-3].strip()
    return raw


# Максимальное время ожидания ответа от Gemini API.
# Без timeout gunicorn worker заблокируется на всё время AI-ответа (10–60 сек).
GEMINI_REQUEST_TIMEOUT = int(os.environ.get('GEMINI_REQUEST_TIMEOUT', '45'))


def generate_exam_with_ai(
    teacher,
    title: str,
    theme: str,
    difficulty: str,
    question_count: int,
    file_content: str | None,
) -> Exam:
    api_key = os.environ.get('GEMINI_API_KEY', '')

    if not api_key:
        logger.info('GEMINI_API_KEY not set, using mock generator')
        data = _mock_generate(title, theme, question_count)
        return _create_exam_from_data(teacher, title, theme, difficulty, data)

    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(title, theme, difficulty, question_count, file_content)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                # Timeout предотвращает блокировку gunicorn workerов при медленном AI.
                timeout=GEMINI_REQUEST_TIMEOUT,
            ),
        )

        raw = _clean_json_response(response.text)
        data = json.loads(raw)
        logger.info('Gemini generated exam "%s" with %d questions', title, len(data.get('questions', [])))

    except json.JSONDecodeError as e:
        logger.warning('Gemini returned invalid JSON, using mock: %s', e)
        data = _mock_generate(title, theme, question_count)
    except Exception as e:
        logger.error('Gemini API error (%s), using mock fallback: %s', type(e).__name__, e)
        data = _mock_generate(title, theme, question_count)

    return _create_exam_from_data(teacher, title, theme, difficulty, data)
