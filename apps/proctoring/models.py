from django.db import models
from django.conf import settings
from django.utils.timezone import now as tz_now

from apps.exams.models import Stream, Question, Option

User = settings.AUTH_USER_MODEL

class ExamAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'В процессе'
        COMPLETED = 'COMPLETED', 'Завершён'
        TERMINATED = 'TERMINATED', 'Принудительно завершён'

    stream = models.ForeignKey(Stream, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='attempts',
        limit_choices_to={'role': 'STUDENT'},
        verbose_name='Студент'
    )
    score = models.PositiveIntegerField(default=0, verbose_name='Балл')
    grade = models.PositiveIntegerField(blank=True, null=True, verbose_name='Оценка')
    status = models.CharField(
        max_length=15, choices=Status.choices,
        default=Status.IN_PROGRESS, verbose_name='Статус',
        db_index=True
    )
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(blank=True, null=True)
    screen_recording = models.FileField(upload_to='recordings/screen/', blank=True, null=True)
    face_recording = models.FileField(upload_to='recordings/face/', blank=True, null=True)

    rules_accepted_at = models.DateTimeField(
        blank=True, null=True,
        verbose_name='Правила приняты в'
    )
    workplace_ready_at = models.DateTimeField(
        blank=True, null=True,
        verbose_name='Место подготовлено в'
    )

    class Meta:
        verbose_name = 'Попытка сдачи'
        verbose_name_plural = 'Попытки сдачи'
        unique_together = [('stream', 'student')]
        indexes = [
            # StreamStudentsView: фильтр по stream + exam учителя
            models.Index(fields=['stream', 'status'], name='attempt_stream_status_idx'),
            # StudentResultsView: список попыток студента сортированных по дате/баллу
            models.Index(fields=['student', '-end_time'], name='attempt_student_endtime_idx'),
            models.Index(fields=['student', '-score'], name='attempt_student_score_idx'),
        ]

    def __str__(self):
        return f"{self.student.email} — {self.stream.exam.title}"

    @property
    def duration_seconds(self):
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        return 0

    @property
    def duration_formatted(self):
        secs = self.duration_seconds
        if not secs:
            return '—'
        hours = secs // 3600
        minutes = (secs % 3600) // 60
        if hours:
            return f"{hours}ч.{minutes:02d}м."
        return f"{minutes}м."

    @property
    def violations_count(self):
        # FIXED RISK-1: используем len() вместо .count() —
        # если violations prefetch-нуты, len() читает кэш без SQL запроса.
        # Если annotated violations_count присутствует — он имеет приоритет через serializer.
        return len(self.violations.all())

    @property
    def remaining_seconds(self) -> int:
        if self.status != ExamAttempt.Status.IN_PROGRESS:
            return 0
        exam_duration_secs = self.stream.exam.duration_minutes * 60
        elapsed = int((tz_now() - self.start_time).total_seconds())
        return max(0, exam_duration_secs - elapsed)

    @staticmethod
    def calculate_grade(score: int, max_score: int) -> int:
        if max_score <= 0:
            return 1
        percentage = (score / max_score) * 100
        if percentage >= 90:
            return 5
        elif percentage >= 75:
            return 4
        elif percentage >= 60:
            return 3
        elif percentage >= 41:
            return 2
        return 1


class AnswerAttempt(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(Option, on_delete=models.SET_NULL, blank=True, null=True)
    text_answer = models.TextField(blank=True, null=True)
    score_earned = models.PositiveIntegerField(default=0)
    is_manually_graded = models.BooleanField(default=False, verbose_name='Проверено вручную')

    class Meta:
        verbose_name = 'Ответ студента'
        verbose_name_plural = 'Ответы студентов'
        unique_together = [('attempt', 'question')]
        indexes = [
            # AttemptAnswersView + manual_grade_answer: ответы по attempt_id
            models.Index(fields=['attempt'], name='answer_attempt_idx'),
        ]

    def __str__(self):
        return f"Ответ Q{self.question_id} от {self.attempt.student.email}"


class Violation(models.Model):
    class ViolationType(models.TextChoices):
        FACE_NOT_IN_FRAME = 'face_not_in_frame', 'Лицо не в рамке'
        FACE_NOT_DETECTED = 'face_not_detected', 'Лицо не обнаружено'
        MULTIPLE_FACES = 'multiple_faces', 'Несколько лиц'
        NOISE_DETECTED = 'noise_detected', 'Обнаружен шум'
        TAB_SWITCH = 'tab_switch', 'Переключение вкладки/экрана'
        SUSPICIOUS_EYE_MOVEMENT = 'suspicious_eye_movement', 'Подозрительное движение глаз'
        PHONE_DETECTED = 'phone_detected', 'Использование телефона/устройств'

    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name='violations')
    violation_type = models.CharField(max_length=30, choices=ViolationType.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Нарушение'
        verbose_name_plural = 'Нарушения'

    def __str__(self):
        return f"Нарушение «{self.get_violation_type_display()}» — Attempt#{self.attempt_id}"


class TutorialVideo(models.Model):
    title = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, null=True, verbose_name='Описание')
    video_file = models.FileField(upload_to='tutorials/', verbose_name='Файл видео')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Обучающее видео'
        verbose_name_plural = 'Обучающие видео'

    def __str__(self):
        return self.title
