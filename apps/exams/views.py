import logging

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Count, Prefetch, Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsTeacher
from .models import Exam, Question, Option, Stream
from .serializers import (
    ExamSerializer, ExamCreateSerializer, ExamFullUpdateSerializer,
    QuestionSerializer, QuestionCreateSerializer, QuestionSummarySerializer,
    OptionSerializer, OptionCreateSerializer,
    StreamSerializer, StreamCreateSerializer,
    AIGenerateSerializer, SetUniformScoreSerializer
)
from .services import generate_exam_with_ai

logger = logging.getLogger(__name__)

class ExamViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ExamCreateSerializer
        return ExamSerializer

    def get_queryset(self):
        # FIXED ARCH-1: annotate вместо N+1 для questions_count и total_questions_score.
        # ExamSerializer читает questions_count/total_questions_score из аннотации — доп. запросов нет.
        return (
            Exam.objects
            .filter(teacher=self.request.user)
            .annotate(
                questions_count_db=Count('questions', distinct=True),
                total_score_db=Sum('questions__score'),
            )
            .order_by('-created_at')
        )

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ExamCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.save(teacher=request.user)
        return Response(ExamSerializer(exam).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = ExamCreateSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()
        return Response(ExamSerializer(exam).data)

    @action(detail=True, methods=['put', 'patch'])
    def full_update(self, request, pk=None):
        instance = self.get_object()
        serializer = ExamFullUpdateSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()
        return Response(ExamSerializer(exam).data)


# Max pages to parse from a teacher-uploaded PDF.
# A 10 000-page PDF would block the gunicorn worker for minutes.
_MAX_PDF_PAGES = 100


def _extract_file_content(uploaded_file) -> str:
    name = uploaded_file.name.lower()
    if name.endswith('.pdf'):
        try:
            import pdfplumber
            parts = []
            with pdfplumber.open(uploaded_file) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= _MAX_PDF_PAGES:
                        logger.warning(
                            'PDF "%s" truncated at %d pages for AI generation',
                            uploaded_file.name, _MAX_PDF_PAGES,
                        )
                        break
                    t = page.extract_text()
                    if t:
                        parts.append(t)
            return '\n'.join(parts)
        except Exception as e:
            logger.warning(
                'Failed to parse PDF "%s" with pdfplumber (%s: %s); falling back to raw bytes',
                uploaded_file.name, type(e).__name__, e,
            )
            uploaded_file.seek(0)
            return uploaded_file.read().decode('utf-8', errors='ignore')
    elif name.endswith('.docx'):
        try:
            import docx
            doc = docx.Document(uploaded_file)
            return '\n'.join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.warning(
                'Failed to parse DOCX "%s" (%s: %s); falling back to raw bytes',
                uploaded_file.name, type(e).__name__, e,
            )
            uploaded_file.seek(0)
            return uploaded_file.read().decode('utf-8', errors='ignore')
    try:
        return uploaded_file.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning('Failed to read file "%s" as text: %s', uploaded_file.name, e)
        return ''


class AIGenerateExamView(APIView):
    permission_classes = [IsTeacher]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = AIGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        file_content = None
        if 'file' in request.FILES:
            file_obj = request.FILES['file']
            if file_obj.size > 10 * 1024 * 1024:
                return Response({'detail': 'Размер файла превышает 10 МБ.'}, status=status.HTTP_400_BAD_REQUEST)
            file_content = _extract_file_content(file_obj)

        exam = generate_exam_with_ai(
            teacher=request.user,
            title=data['title'],
            theme=data.get('theme', ''),
            difficulty=data.get('difficulty', Exam.Difficulty.MEDIUM),
            question_count=data.get('question_count', 10),
            file_content=file_content,
        )
        return Response(ExamSerializer(exam).data, status=status.HTTP_201_CREATED)


class QuestionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]

    def get_serializer_class(self):
        if self.action == 'list':
            return QuestionSummarySerializer
        return QuestionCreateSerializer

    def get_queryset(self):
        return (
            Question.objects
            .filter(
                exam_id=self.kwargs['exam_pk'],
                exam__teacher=self.request.user,
            )
            .select_related('exam__teacher')   # нужен для ExamSerializer внутри list()
            .prefetch_related('options')
        )

    def perform_create(self, serializer):
        exam = get_object_or_404(
            Exam, pk=self.kwargs['exam_pk'], teacher=self.request.user
        )
        serializer.save(exam=exam)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        # exam уже загружен через select_related в первом вопросе — без доп. SQL
        exam = qs.first()
        if exam is None:
            # Пустой exam — проверяем существование экзамена (нет вопросов)
            exam_obj = get_object_or_404(
                Exam.objects.annotate(
                    questions_count_db=Count('questions', distinct=True),
                    total_score_db=Sum('questions__score'),
                ),
                pk=self.kwargs['exam_pk'],
                teacher=request.user,
            )
            return Response({'exam': ExamSerializer(exam_obj).data, 'questions': []})

        exam_obj = (
            Exam.objects
            .annotate(
                questions_count_db=Count('questions', distinct=True),
                total_score_db=Sum('questions__score'),
            )
            .get(pk=exam.exam_id)
        )
        return Response({
            'exam': ExamSerializer(exam_obj).data,
            'questions': QuestionSerializer(qs, many=True).data,
        })


class OptionViewSet(viewsets.ModelViewSet):
    serializer_class = OptionCreateSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        return Option.objects.filter(
            question_id=self.kwargs['question_pk'],
            question__exam__teacher=self.request.user,
        )

    def perform_create(self, serializer):
        question = get_object_or_404(
            Question,
            pk=self.kwargs['question_pk'],
            exam__teacher=self.request.user,
        )
        serializer.save(question=question)


class StreamViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTeacher]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return StreamCreateSerializer
        return StreamSerializer

    def get_queryset(self):
        # FIXED ARCH-2: annotate students_count — убираем N+1 .count() в StreamSerializer.
        exam_pk = self.kwargs.get('exam_pk')
        qs = Stream.objects.annotate(students_count_db=Count('attempts'))
        if exam_pk:
            return qs.filter(exam_id=exam_pk, exam__teacher=self.request.user)
        return qs.filter(exam__teacher=self.request.user)

    def perform_create(self, serializer):
        exam = get_object_or_404(Exam, pk=self.kwargs['exam_pk'], teacher=self.request.user)
        serializer.save(exam=exam)

    def create(self, request, *args, **kwargs):
        serializer = StreamCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = get_object_or_404(Exam, pk=self.kwargs['exam_pk'], teacher=request.user)
        stream = serializer.save(exam=exam)
        return Response(
            StreamSerializer(stream, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

class SetUniformScoreView(APIView):
    permission_classes = [IsTeacher]

    def post(self, request, exam_pk):
        exam = get_object_or_404(Exam, pk=exam_pk, teacher=request.user)
        serializer = SetUniformScoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        score = serializer.validated_data['score']

        # FIXED RISK-3: transaction.atomic — update+save атомарны.
        # Используем возвращаемое значение update() — не нужен отдельный COUNT(*).
        with transaction.atomic():
            updated = exam.questions.update(score=score)
            new_max = updated * score  # updated == кол-во затронутых строк, не нужен COUNT
            exam.max_score = new_max
            exam.save(update_fields=['max_score'])

        return Response({
            'updated_questions': updated,
            'score_per_question': score,
            'new_max_score': new_max,
        })

class TeacherResultsView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request):
        streams_qs = Stream.objects.annotate(students_count=Count('attempts'))
        exams_qs = (
            Exam.objects
            .filter(teacher=request.user)
            .prefetch_related(Prefetch('streams', queryset=streams_qs))
            .order_by('-created_at')
        )

        # Paginate: without this a teacher with 500 exams returns a huge JSON in one shot.
        paginator = PageNumberPagination()
        paginator.page_size = django_settings.REST_FRAMEWORK.get('PAGE_SIZE', 20)
        page = paginator.paginate_queryset(exams_qs, request)

        def _serialize(exam_list):
            return [
                {
                    'id': exam.id,
                    'title': exam.title,
                    'streams': [
                        {
                            'id': s.id,
                            'title': s.title,
                            'students_count': s.students_count,
                            'invite_url': request.build_absolute_uri(
                                reverse(
                                    'proctoring:student_exam_start',
                                    kwargs={'uuid': s.access_link_uuid},
                                )
                            ),
                        }
                        for s in exam.streams.all()
                    ],
                }
                for exam in exam_list
            ]

        if page is not None:
            return paginator.get_paginated_response(_serialize(page))
        return Response(_serialize(exams_qs))
