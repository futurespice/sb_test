from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', 'Студент'
        TEACHER = 'TEACHER', 'Учитель'

    class Language(models.TextChoices):
        RUSSIAN = 'ru', 'Русский'
        KYRGYZ = 'ky', 'Кыргызча'

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT, db_index=True)
    language = models.CharField(
        max_length=5, choices=Language.choices,
        default=Language.RUSSIAN, verbose_name='Язык интерфейса'
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def get_full_name(self):
        name = f"{self.last_name} {self.first_name}".strip()
        return name if name else self.email

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"
