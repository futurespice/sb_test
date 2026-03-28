from django.contrib import admin

from .models import Exam, Question, Option, Stream


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    fields = ['text', 'image', 'is_correct', 'order']


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    fields = ['text', 'image', 'type', 'score', 'order', 'expected_answer', 'min_answer_length']
    show_change_link = True


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['title', 'teacher', 'difficulty', 'duration_minutes', 'max_score', 'exam_date', 'created_at']
    list_filter = ['difficulty', 'microphone_status', 'require_screen_record', 'require_face_record']
    search_fields = ['title', 'theme', 'teacher__email', 'teacher__first_name', 'teacher__last_name']
    readonly_fields = ['created_at']
    raw_id_fields = ['teacher']
    inlines = [QuestionInline]
    ordering = ['-created_at']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'exam', 'type', 'score', 'order']
    list_filter = ['type']
    search_fields = ['text', 'exam__title']
    raw_id_fields = ['exam']
    inlines = [OptionInline]
    ordering = ['exam', 'order']


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ['title', 'exam', 'access_link_uuid', 'mic_enabled', 'created_at']
    search_fields = ['title', 'exam__title']
    raw_id_fields = ['exam']
    readonly_fields = ['access_link_uuid', 'created_at']
    ordering = ['-created_at']
