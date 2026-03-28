from django.contrib import admin

from .models import ExamAttempt, AnswerAttempt, Violation, TutorialVideo


class AnswerInline(admin.TabularInline):
    model = AnswerAttempt
    extra = 0
    fields = ['question', 'selected_option', 'text_answer', 'score_earned', 'is_manually_graded']
    readonly_fields = ['question', 'selected_option', 'text_answer']
    can_delete = False


class ViolationInline(admin.TabularInline):
    model = Violation
    extra = 0
    fields = ['violation_type', 'created_at']
    readonly_fields = ['violation_type', 'created_at']
    can_delete = False


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'stream', 'score', 'grade', 'status',
        'start_time', 'end_time', 'violations_count_display',
    ]
    list_filter = ['status']
    search_fields = [
        'student__email', 'student__first_name', 'student__last_name',
        'stream__exam__title', 'stream__title',
    ]
    readonly_fields = ['score', 'grade', 'start_time', 'end_time', 'rules_accepted_at', 'workplace_ready_at']
    raw_id_fields = ['student', 'stream']
    inlines = [AnswerInline, ViolationInline]
    ordering = ['-start_time']

    @admin.display(description='Нарушений')
    def violations_count_display(self, obj):
        return obj.violations.count()

    actions = ['terminate_attempts']

    @admin.action(description='Принудительно завершить выбранные попытки')
    def terminate_attempts(self, request, queryset):
        from django.utils.timezone import now
        updated = queryset.filter(
            status=ExamAttempt.Status.IN_PROGRESS
        ).update(status=ExamAttempt.Status.TERMINATED, end_time=now())
        self.message_user(request, f'{updated} попыток завершено принудительно.')


@admin.register(TutorialVideo)
class TutorialVideoAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at']
    search_fields = ['title']
    ordering = ['-created_at']
