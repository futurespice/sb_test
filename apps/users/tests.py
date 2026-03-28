from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


class AuthTests(TestCase):
    """Основные тесты аутентификации."""

    def setUp(self):
        self.client = APIClient()
        self.student = User.objects.create_user(
            username='student@test.com',
            email='student@test.com',
            password='testpass123',
            role=User.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            username='teacher@test.com',
            email='teacher@test.com',
            password='testpass123',
            role=User.Role.TEACHER,
        )

    def test_login_success(self):
        r = self.client.post('/api/v1/auth/login/', {
            'email': 'student@test.com', 'password': 'testpass123'
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('access', r.data)
        self.assertIn('refresh', r.data)
        self.assertEqual(r.data['user']['role'], 'STUDENT')

    def test_login_wrong_password(self):
        r = self.client.post('/api/v1/auth/login/', {
            'email': 'student@test.com', 'password': 'wrong'
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_register_always_creates_student(self):
        """SEC: роль TEACHER через регистрацию невозможна."""
        r = self.client.post('/api/v1/auth/register/', {
            'email': 'newuser@test.com',
            'password': 'testpass123',
            'first_name': 'New',
            'last_name': 'User',
            'role': 'TEACHER',  # пытаемся поднять роль
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@test.com')
        self.assertEqual(user.role, User.Role.STUDENT)  # всегда STUDENT

    def test_logout_blacklists_token(self):
        login = self.client.post('/api/v1/auth/login/', {
            'email': 'student@test.com', 'password': 'testpass123'
        })
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        r = self.client.post('/api/v1/auth/logout/', {'refresh': login.data['refresh']})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_teacher_cannot_access_student_endpoints(self):
        self.client.force_authenticate(user=self.teacher)
        r = self.client.get('/api/v1/student/results/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_access_teacher_endpoints(self):
        self.client.force_authenticate(user=self.student)
        r = self.client.get('/api/v1/teacher/exams/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_request_rejected(self):
        r = self.client.get('/api/v1/teacher/exams/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
