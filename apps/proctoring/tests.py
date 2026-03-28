from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.exams.models import Exam, Question, Option, Stream
from apps.proctoring.models import ExamAttempt, AnswerAttempt

User = get_user_model()


class StudentExamFlowTests(TestCase):
    """Критический путь: студент проходит экзамен."""

    def setUp(self):
        self.client = APIClient()
        self.teacher = User.objects.create_user(
            username='teacher@test.com',
            email='teacher@test.com',
            password='testpass123',
            role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student@test.com',
            email='student@test.com',
            password='testpass123',
            role=User.Role.STUDENT,
        )
        # Создаём экзамен с вопросом
        self.exam = Exam.objects.create(
            title='Физика',
            teacher=self.teacher,
            duration_minutes=60,
            max_score=10,
        )
        self.question = Question.objects.create(
            exam=self.exam,
            text='Что такое ньютон?',
            type=Question.Type.CHOICE,
            score=10,
            order=1,
        )
        self.correct_option = Option.objects.create(
            question=self.question, text='Учёный', is_correct=True, order=1
        )
        Option.objects.create(
            question=self.question, text='Аптекарь', is_correct=False, order=2
        )
        self.stream = Stream.objects.create(
            exam=self.exam, title='Поток-1'
        )
        self.client.force_authenticate(user=self.student)

    def test_student_can_start_exam(self):
        r = self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('attempt_id', r.data)
        self.assertIn('questions', r.data)
        self.assertEqual(len(r.data['questions']), 1)

    def test_questions_hide_is_correct_from_student(self):
        """SEC: студент не должен видеть is_correct."""
        r = self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        options = r.data['questions'][0].get('options', [])
        for opt in options:
            self.assertNotIn('is_correct', opt)

    def test_submit_correct_answer_scores_full(self):
        # Сначала открываем экзамен
        self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        r = self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            {'answers': [{
                'question': self.question.pk,
                'selected_option': self.correct_option.pk,
            }]},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['score'], 10)
        self.assertEqual(r.data['grade'], 5)

    def test_submit_wrong_answer_scores_zero(self):
        wrong = Option.objects.get(question=self.question, is_correct=False)
        self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        r = self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            {'answers': [{
                'question': self.question.pk,
                'selected_option': wrong.pk,
            }]},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['score'], 0)

    def test_empty_submit_rejected(self):
        """Пустой submit должен вернуть 400, а не сжигать попытку."""
        self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        r = self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            {'answers': []},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        # попытка не завершена
        attempt = ExamAttempt.objects.get(stream=self.stream, student=self.student)
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)

    def test_double_submit_rejected(self):
        """Двойной submit должен вернуть 400 на второй запрос."""
        self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        payload = {'answers': [{
            'question': self.question.pk,
            'selected_option': self.correct_option.pk,
        }]}
        self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            payload, format='json'
        )
        r2 = self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            payload, format='json'
        )
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_answer_stuffing_rejected(self):
        """Ответ на чужой экзамен игнорируется."""
        other_exam = Exam.objects.create(
            title='Чужой', teacher=self.teacher,
            duration_minutes=60, max_score=10,
        )
        other_q = Question.objects.create(
            exam=other_exam, text='Чужой вопрос',
            type=Question.Type.CHOICE, score=10, order=1,
        )
        other_opt = Option.objects.create(
            question=other_q, text='Ответ', is_correct=True, order=1
        )
        self.client.get(f'/api/v1/student/exam/{self.stream.access_link_uuid}/')
        # Отправляем вопрос из чужого экзамена — должен быть проигнорирован
        r = self.client.post(
            f'/api/v1/student/exam/{self.stream.access_link_uuid}/submit/',
            {'answers': [{
                'question': other_q.pk,  # вопрос из ДРУГОГО экзамена
                'selected_option': other_opt.pk,
            }]},
            format='json',
        )
        # Чужой вопрос проигнорирован — ответов ноль, empty list guard вернёт 400
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class GradeCalculationTests(TestCase):
    """Тесты расчёта оценки."""

    def test_grade_boundaries(self):
        from apps.proctoring.models import ExamAttempt
        cases = [
            (100, 100, 5),  # 100% → 5
            (90, 100, 5),   # 90% → 5
            (89, 100, 4),   # 89% → 4
            (75, 100, 4),   # 75% → 4
            (74, 100, 3),   # 74% → 3
            (60, 100, 3),   # 60% → 3
            (59, 100, 2),   # 59% → 2
            (41, 100, 2),   # 41% → 2
            (40, 100, 1),   # 40% → 1
            (0, 100, 1),    # 0%  → 1
            (0, 0, 1),      # max=0 → 1 (не краш)
        ]
        for score, max_s, expected in cases:
            with self.subTest(score=score, max_score=max_s):
                self.assertEqual(
                    ExamAttempt.calculate_grade(score, max_s), expected
                )
