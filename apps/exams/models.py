from django.db import models
from django.db.models import Sum
from django.conf import settings
import uuid

User = settings.AUTH_USER_MODEL

class Exam(models.Model):
    class Difficulty(models.TextChoices):
        EASY = 'EASY', 'Лёгкий'
        MEDIUM = 'MEDIUM', 'Средний'
        HARD = 'HARD', 'Сложный'

    class MicrophoneStatus(models.TextChoices):
        ON = 'ON', 'Включен'
        OFF = 'OFF', 'Выключен'
        HYBRID = 'HYBRID', 'Гибридное'

    title = models.CharField(max_length=255, verbose_name='Название')
    theme = models.CharField(max_length=255, blank=True, null=True, verbose_name='Тема')
    difficulty = models.CharField(
        max_length=10, choices=Difficulty.choices, blank=True, null=True,
        verbose_name='Сложность'
    )
    duration_minutes = models.PositiveIntegerField(default=60, verbose_name='Длительность (мин)')
    max_score = models.PositiveIntegerField(default=100, verbose_name='Макс. балл')
    teacher = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='exams',
        limit_choices_to={'role': 'TEACHER'},
        verbose_name='Учитель'
    )
    exam_date = models.DateField(blank=True, null=True, verbose_name='Дата проведения')
    microphone_status = models.CharField(
        max_length=10, choices=MicrophoneStatus.choices,
        default=MicrophoneStatus.OFF, verbose_name='Состояние микрофона'
    )
    require_screen_record = models.BooleanField(default=False, verbose_name='Запись экрана')
    require_face_record = models.BooleanField(default=False, verbose_name='Запись лица')

    max_violations = models.PositiveIntegerField(
        default=4,
        verbose_name='Макс. нарушений до аннуляции'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Экзамен'
        verbose_name_plural = 'Экзамены'
        ordering = ['-created_at']
        indexes = [
            # Фильтр "ExamViewSet.get_queryset" — список экзаменов учителя сортированных по дате
            models.Index(fields=['teacher', '-created_at'], name='exam_teacher_created_idx'),
        ]

    def __str__(self):
        return self.title

    @property
    def questions_total_score(self):
        return self.questions.aggregate(total=Sum('score'))['total'] or 0


class Question(models.Model):
    class Type(models.TextChoices):
        CHOICE = 'CHOICE', 'Текстовое поле (4 варианта)'
        PHOTO_CHOICE = 'PHOTO_CHOICE', 'Фото ответ (4 варианта-фото)'
        INTERACTIVE = 'INTERACTIVE', 'Интерактивный ответ (свободный текст)'

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField(verbose_name='Текст вопроса')
    image = models.ImageField(upload_to='questions/', blank=True, null=True, verbose_name='Изображение')
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.CHOICE, verbose_name='Тип')
    score = models.PositiveIntegerField(default=1, verbose_name='Балл')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')
    expected_answer = models.TextField(blank=True, null=True, verbose_name='Ожидаемый ответ')
    min_answer_length = models.PositiveIntegerField(
        default=0,
        verbose_name='Мин. длина ответа (символов)',
        help_text='Для INTERACTIVE. 0 = нет ограничения.'
    )

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Вопрос'
        verbose_name_plural = 'Вопросы'
        indexes = [
            # Фильтр вопросов через exam_id в QuestionViewSet + submit_exam_answers
            models.Index(fields=['exam', 'order'], name='question_exam_order_idx'),
        ]

    def __str__(self):
        return f"{self.exam.title} - Q{self.order}: {self.text[:50]}"


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    text = models.CharField(max_length=500, blank=True, null=True, verbose_name='Текст')
    image = models.ImageField(upload_to='options/', blank=True, null=True, verbose_name='Изображение')
    is_correct = models.BooleanField(default=False, verbose_name='Правильный')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Вариант ответа'
        verbose_name_plural = 'Варианты ответов'

    def __str__(self):
        marker = '✓' if self.is_correct else '✗'
        return f"[{marker}] {self.text or 'фото'} (Q#{self.question_id})"


class Stream(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='streams')
    title = models.CharField(max_length=255, verbose_name='Название потока')
    access_link_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    mic_enabled = models.BooleanField(default=False, verbose_name='Микрофон включён (поток)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Поток'
        verbose_name_plural = 'Потоки'
        indexes = [
            # StreamViewSet фильтрует по exam_id, TeacherResultsView — prefetch streams по exam
            models.Index(fields=['exam'], name='stream_exam_idx'),
        ]

    def __str__(self):
        return f"{self.title} ({self.exam.title})"
