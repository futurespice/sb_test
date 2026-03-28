from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.exams.models import Exam, Question, Option, Stream

User = get_user_model()


class ExamCRUDTests(TestCase):
    """Тесты CRUD экзаменов и изоляции по учителю."""

    def setUp(self):
        self.client = APIClient()
        self.teacher = User.objects.create_user(
            username='teacher@test.com',
            email='teacher@test.com',
            password='testpass123',
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            username='other@test.com',
            email='other@test.com',
            password='testpass123',
            role=User.Role.TEACHER,
        )
        self.client.force_authenticate(user=self.teacher)

    def _make_exam(self, teacher=None):
        return Exam.objects.create(
            title='Тестовый экзамен',
            teacher=teacher or self.teacher,
            duration_minutes=60,
            max_score=100,
        )

    def test_create_exam(self):
        r = self.client.post('/api/v1/teacher/exams/', {
            'title': 'Математика',
            'duration_minutes': 90,
            'max_score': 50,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Exam.objects.filter(teacher=self.teacher).count(), 1)

    def test_list_only_own_exams(self):
        """IDOR: учитель видит только свои экзамены."""
        self._make_exam()                          # свой
        self._make_exam(teacher=self.other_teacher)  # чужой
        r = self.client.get('/api/v1/teacher/exams/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = [e['id'] for e in r.data['results']]
        for exam_id in ids:
            self.assertEqual(
                Exam.objects.get(pk=exam_id).teacher, self.teacher
            )

    def test_cannot_access_other_teacher_exam(self):
        """IDOR: нельзя получить экзамен чужого учителя."""
        other_exam = self._make_exam(teacher=self.other_teacher)
        r = self.client.get(f'/api/v1/teacher/exams/{other_exam.pk}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_exam(self):
        exam = self._make_exam()
        r = self.client.delete(f'/api/v1/teacher/exams/{exam.pk}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Exam.objects.filter(pk=exam.pk).exists())

    def test_cannot_delete_other_teacher_exam(self):
        other_exam = self._make_exam(teacher=self.other_teacher)
        r = self.client.delete(f'/api/v1/teacher/exams/{other_exam.pk}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Exam.objects.filter(pk=other_exam.pk).exists())


class StreamTests(TestCase):
    """Тесты потоков."""

    def setUp(self):
        self.client = APIClient()
        self.teacher = User.objects.create_user(
            username='teacher@test.com',
            email='teacher@test.com',
            password='testpass123',
            role=User.Role.TEACHER,
        )
        self.exam = Exam.objects.create(
            title='Тест',
            teacher=self.teacher,
            duration_minutes=60,
            max_score=100,
        )
        self.client.force_authenticate(user=self.teacher)

    def test_create_stream_generates_uuid(self):
        r = self.client.post(
            f'/api/v1/teacher/exams/{self.exam.pk}/streams/',
            {'title': 'Поток-1'},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn('access_link_uuid', r.data)
        self.assertIn('invite_url', r.data)

    def test_stream_invite_url_uses_reverse(self):
        """invite_url должен содержать UUID, а не хардкодед path."""
        r = self.client.post(
            f'/api/v1/teacher/exams/{self.exam.pk}/streams/',
            {'title': 'Поток-1'},
        )
        self.assertIn('/student/exam/', r.data['invite_url'])
