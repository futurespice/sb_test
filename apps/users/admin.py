from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'role', 'is_active', 'date_joined']
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']
    readonly_fields = ['date_joined', 'last_login']

    # Поля при редактировании существующего пользователя
    fieldsets = UserAdmin.fieldsets + (
        ('Роль и язык', {'fields': ('role', 'language')}),
    )

    # Поля при создании нового пользователя
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Роль и язык', {'fields': ('role', 'language', 'email', 'first_name', 'last_name')}),
    )

    actions = ['make_teacher', 'make_student']

    @admin.action(description='Назначить роль: Учитель')
    def make_teacher(self, request, queryset):
        updated = queryset.update(role=User.Role.TEACHER)
        self.message_user(request, f'{updated} пользователей назначены учителями.')

    @admin.action(description='Назначить роль: Студент')
    def make_student(self, request, queryset):
        updated = queryset.update(role=User.Role.STUDENT)
        self.message_user(request, f'{updated} пользователей назначены студентами.')
