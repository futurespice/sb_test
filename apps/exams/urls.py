from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ExamViewSet, AIGenerateExamView,
    QuestionViewSet, OptionViewSet, SetUniformScoreView,
    StreamViewSet, TeacherResultsView
)

app_name = 'exams'

router = DefaultRouter()
router.register(r'teacher/exams', ExamViewSet, basename='teacher-exams')
router.register(
    r'teacher/exams/(?P<exam_pk>[^/.]+)/questions',
    QuestionViewSet,
    basename='teacher-exam-questions',
)
router.register(
    r'teacher/exams/(?P<exam_pk>[^/.]+)/questions/(?P<question_pk>[^/.]+)/options',
    OptionViewSet,
    basename='teacher-question-options',
)
router.register(
    r'teacher/exams/(?P<exam_pk>[^/.]+)/streams',
    StreamViewSet,
    basename='teacher-exam-streams',
)

# ВАЖНО: явные path() должны стоять ПЕРЕД include(router.urls).
# Роутер регистрирует teacher/exams/{pk}/ и если router пойдёт первым,
# 'ai-generate' будет интерпретирован как {pk} — ExamViewSet вернёт 404.
urlpatterns = [
    path('teacher/exams/ai-generate/', AIGenerateExamView.as_view(), name='ai_generate'),
    path('teacher/exams/<int:exam_pk>/questions/set-uniform-score/', SetUniformScoreView.as_view(), name='set_uniform_score'),
    path('teacher/results/', TeacherResultsView.as_view(), name='teacher_results'),
    # Роутер обязательно в конце
    path('', include(router.urls)),
]
