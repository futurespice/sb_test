from rest_framework import permissions
from django.contrib.auth import get_user_model

User = get_user_model()

class IsTeacher(permissions.BasePermission):
    message = 'Доступ разрешён только учителям.'

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.TEACHER

class IsStudent(permissions.BasePermission):
    message = 'Доступ разрешён только студентам.'

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.STUDENT
