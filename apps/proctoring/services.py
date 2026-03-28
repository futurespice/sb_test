import logging

from django.db import transaction
from django.db.models import Count, Sum
from django.utils.timezone import now

from apps.exams.models import Question, Option
from apps.proctoring.models import ExamAttempt, AnswerAttempt, Violation

logger = logging.getLogger(__name__)


class ExamValidationError(ValueError):
    """
    Domain exception for exam business rule violations.
    Raised by service layer, caught and converted to HTTP 400 in views.
    Keeps services free of HTTP/DRF concepts.
    """
    pass


@transaction.atomic
def submit_exam_answers(attempt: ExamAttempt, answers_data: list) -> ExamAttempt:
    """
    Save student answers atomically.
    FIXED: заменен N+1 (до 90 SQL на 30 вопросов) на 2 запроса + 1 bulk_create.
    """
    stream = attempt.stream
    exam = stream.exam

    # Один запрос: все вопросы экзамена + options в prefetch-кэше
    questions_map: dict[int, Question] = {
        q.id: q
        for q in Question.objects.filter(exam=exam).prefetch_related('options')
    }

    # Один запрос: уже отвеченные вопросы (защита от double-submit)
    answered_ids: set[int] = set(
        AnswerAttempt.objects
        .filter(attempt=attempt)
        .values_list('question_id', flat=True)
    )

    total_score = 0
    answers_to_create: list[AnswerAttempt] = []

    for ans in answers_data:
        q_id = ans.get('question')
        opt_id = ans.get('selected_option')
        text_ans = ans.get('text_answer', '') or ''

        question = questions_map.get(q_id)
        if not question or q_id in answered_ids:
            continue

        # options уже в prefetch-кэше — без SQL
        options_map: dict[int, Option] = {o.id: o for o in question.options.all()}
        option = options_map.get(opt_id) if opt_id else None

        score_earned = 0
        if question.type in (Question.Type.CHOICE, Question.Type.PHOTO_CHOICE):
            if option and option.is_correct:
                score_earned = question.score

        if question.type == Question.Type.INTERACTIVE:
            min_len = question.min_answer_length
            if min_len > 0 and len(text_ans.strip()) < min_len:
                raise ExamValidationError(
                    f'Ответ на вопрос {question.order} должен быть не короче {min_len} символов.'
                )

        answers_to_create.append(AnswerAttempt(
            attempt=attempt,
            question=question,
            selected_option=option,
            text_answer=text_ans,
            score_earned=score_earned,
        ))
        total_score += score_earned

    # Один bulk INSERT вместо N отдельных.
    # ignore_conflicts=True — идемпотентная защита на уровне БД через unique_together(attempt, question).
    if answers_to_create:
        AnswerAttempt.objects.bulk_create(answers_to_create, ignore_conflicts=True)

    attempt.score = total_score
    attempt.grade = ExamAttempt.calculate_grade(total_score, exam.max_score)
    attempt.status = ExamAttempt.Status.COMPLETED
    attempt.end_time = now()
    attempt.save(update_fields=['score', 'grade', 'status', 'end_time'])
    return attempt


@transaction.atomic
def manual_grade_answer(answer: AnswerAttempt, score_earned: int) -> ExamAttempt:
    """
    Teacher grades an interactive answer; recalculates attempt total.
    select_for_update() prevents race condition when two teachers grade
    different answers of the same attempt simultaneously — without it,
    both would read the same stale total and the last writer wins.
    """
    answer.score_earned = score_earned
    answer.is_manually_graded = True
    answer.save(update_fields=['score_earned', 'is_manually_graded'])

    # Lock the attempt row for the duration of this transaction.
    # Guarantees attempt.score == SUM(answer.score_earned) even under concurrency.
    attempt = (
        ExamAttempt.objects
        .select_for_update()
        .select_related('stream__exam')
        .get(pk=answer.attempt_id)
    )
    total = attempt.answers.aggregate(total=Sum('score_earned'))['total'] or 0
    attempt.score = total
    attempt.grade = ExamAttempt.calculate_grade(total, attempt.stream.exam.max_score)
    attempt.save(update_fields=['score', 'grade'])

    return attempt


@transaction.atomic
def record_violation(attempt: ExamAttempt, violation_type: str) -> tuple[int, bool]:
    """
    Record a proctoring violation.
    select_for_update() гарантирует атомарность: нет race condition при
    одновременных запросах с мобильного клиента.
    """
    # Блокируем строку attempt + сразу аннотируем число нарушений через LEFT JOIN — один запрос.
    attempt = (
        ExamAttempt.objects
        .select_for_update()
        .select_related('stream__exam')
        .annotate(violation_count=Count('violations'))
        .get(pk=attempt.pk)
    )

    # Guard: уже завершён (параллельный запрос успел заблокировать первым)
    if attempt.status != ExamAttempt.Status.IN_PROGRESS:
        return attempt.violation_count, True

    Violation.objects.create(
        attempt=attempt,
        violation_type=violation_type,
    )
    # После INSERT: аннотация уже вычислена до вставки, увеличиваем вручную.
    violations_count = attempt.violation_count + 1
    max_v = attempt.stream.exam.max_violations
    terminated = violations_count >= max_v

    if terminated:
        attempt.status = ExamAttempt.Status.TERMINATED
        attempt.end_time = now()
        attempt.save(update_fields=['status', 'end_time'])

    return violations_count, terminated
