import logging
import io
import os
import re
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import generics, status, permissions, filters
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.users.permissions import IsTeacher, IsStudent
from apps.exams.models import Stream, Exam
from apps.exams.serializers import ExamSerializer

from .models import ExamAttempt, AnswerAttempt, Violation, TutorialVideo
from .serializers import (
    AttemptStudentSerializer, StudentResultSerializer, AnswerAttemptSerializer,
    ManualGradeSerializer, ExamSubmitSerializer, ViolationSerializer,
    ViolationCreateSerializer, TutorialVideoSerializer, AttemptPreExamSerializer
)
from .services import submit_exam_answers, manual_grade_answer, record_violation, ExamValidationError

logger = logging.getLogger(__name__)

# Magic bytes for common video formats used in browser recording
_ALLOWED_VIDEO_MAGIC: list[bytes] = [
    b'\x00\x00\x00\x18ftyp',   # MP4
    b'\x00\x00\x00\x1cftyp',   # MP4 variant
    b'\x00\x00\x00\x20ftyp',   # MP4 variant
    b'\x1a\x45\xdf\xa3',       # WebM / MKV
    b'RIFF',                    # WebM via RIFF container (rare)
]


def _is_valid_video(file_obj) -> bool:
    """Validate video by magic bytes, not just Content-Type header."""
    header = file_obj.read(8)
    file_obj.seek(0)
    return any(header.startswith(magic) for magic in _ALLOWED_VIDEO_MAGIC)


# ─── Teacher Views ──────────────────────────────────────────────────────────

class StreamStudentsView(generics.ListAPIView):
    serializer_class = AttemptStudentSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        return (
            ExamAttempt.objects
            .filter(
                stream_id=self.kwargs['stream_pk'],
                stream__exam__teacher=self.request.user,
            )
            # FIXED: include stream__exam__teacher so get_teacher_name() has no extra query
            .select_related('student', 'stream__exam__teacher')
            .prefetch_related('violations')
        )

class StreamStudentsPDFView(APIView):
    permission_classes = [IsTeacher]
    # PDF generation is synchronous and blocks a gunicorn worker for ~2-5 seconds.
    # Throttle prevents 8 concurrent PDFs from exhausting all workers.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'pdf_export'

    def get(self, request, exam_pk, stream_pk):
        stream = get_object_or_404(
            Stream.objects.select_related('exam__teacher'),
            pk=stream_pk,
            exam__teacher=request.user,
        )
        attempts = (
            ExamAttempt.objects
            .filter(stream=stream)
            .select_related('student')
            .order_by('student__last_name', 'student__first_name')
        )
        # Вычисляем count единразды, используем в PDF-заголовке
        attempts_count = attempts.count()

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError:
            return Response({'detail': 'reportlab не установлен'}, status=500)

        font_registered = False
        font_name = 'DejaVuSans'
        font_candidates = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/TTF/DejaVuSans.ttf',
            '/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf',
        ]
        for fp in font_candidates:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, fp))
                    font_registered = True
                    break
                except Exception:
                    continue

        if not font_registered:
            font_name = 'Helvetica'

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=2 * cm, bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        mk = lambda name, parent, **kw: ParagraphStyle(name, parent=styles[parent], fontName=font_name, **kw)

        elements = [
            Paragraph(f"Экзамен: {stream.exam.title}", mk('T', 'Heading1', fontSize=14, spaceAfter=6)),
            Paragraph(f"Поток: {stream.title}", mk('S', 'Heading2', fontSize=11, spaceAfter=12)),
            Paragraph(f"Учитель: {stream.exam.teacher.get_full_name()}  |  Студентов: {attempts_count}", mk('N', 'Normal', fontSize=9)),
            Spacer(1, 0.5 * cm),
        ]

        headers = ['#', 'Студент', 'Email', 'Балл', 'Оценка', 'Время', 'Дата', 'Статус']
        rows = [headers]
        for i, att in enumerate(attempts, 1):
            rows.append([
                str(i), att.student.get_full_name(), att.student.email,
                str(att.score), str(att.grade or '—'), att.duration_formatted,
                att.end_time.strftime('%d.%m.%Y') if att.end_time else '—',
                att.get_status_display(),
            ])

        col_w = [0.8*cm, 4.5*cm, 5*cm, 1.5*cm, 1.5*cm, 2*cm, 2.5*cm, 2.5*cm]
        table = Table(rows, colWidths=col_w, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2D6A9F')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EEF4FB')]),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CCCCCC')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        
        # FIXED SEC-1: re/quote уже импортированы в начале файла.
        def _safe_filename_part(s: str, max_len: int = 30) -> str:
            s = re.sub(r'[^\w\-]', '_', s, flags=re.ASCII)
            return s[:max_len] or 'file'

        safe_exam = _safe_filename_part(stream.exam.title)
        safe_stream = _safe_filename_part(stream.title)
        ascii_name = f'results_{safe_exam}_{safe_stream}.pdf'

        # RFC 5987: filename* — передаём UTF-8 имя безопасно.
        utf8_exam = quote(stream.exam.title[:60], safe='')
        utf8_stream = quote(stream.title[:60], safe='')
        utf8_name = f'results_{utf8_exam}_{utf8_stream}.pdf'

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'
        )
        return response

class AttemptAnswersView(generics.ListAPIView):
    serializer_class = AnswerAttemptSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        attempt = get_object_or_404(
            ExamAttempt,
            pk=self.kwargs['attempt_pk'],
            stream__exam__teacher=self.request.user,
        )
        return attempt.answers.select_related('question', 'selected_option')

class ManualGradeView(APIView):
    permission_classes = [IsTeacher]

    def patch(self, request, answer_pk):
        answer = get_object_or_404(
            AnswerAttempt,
            pk=answer_pk,
            attempt__stream__exam__teacher=request.user,
            question__type='INTERACTIVE',
        )

        # Нельзя проверять ответы пока студент ещё проходит экзамен:
        # submit_exam_answers перезапишет вручной балл при финальном сабмите.
        if answer.attempt.status == ExamAttempt.Status.IN_PROGRESS:
            return Response(
                {'detail': 'Нельзя проверять ответы пока студент проходит экзамен.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ManualGradeSerializer(answer, data=request.data)
        serializer.is_valid(raise_exception=True)

        attempt = manual_grade_answer(answer, serializer.validated_data['score_earned'])

        return Response({
            'answer_id': answer.id,
            'score_earned': answer.score_earned,
            'attempt_score': attempt.score,
            'attempt_grade': attempt.grade,
        })

class StudentRecordingView(APIView):
    permission_classes = [IsTeacher]

    def get(self, request, attempt_pk):
        attempt = get_object_or_404(
            ExamAttempt.objects.select_related('student', 'stream__exam'),
            pk=attempt_pk,
            stream__exam__teacher=request.user,
        )
        return Response({
            'attempt_id': attempt.id,
            'student': attempt.student.get_full_name(),
            'score': attempt.score,
            'grade': attempt.grade,
            'duration_formatted': attempt.duration_formatted,
            'screen_recording': request.build_absolute_uri(attempt.screen_recording.url) if attempt.screen_recording else None,
            'face_recording': request.build_absolute_uri(attempt.face_recording.url) if attempt.face_recording else None,
            'violations': ViolationSerializer(attempt.violations.all(), many=True).data,
        })

class TutorialVideoListView(generics.ListCreateAPIView):
    queryset = TutorialVideo.objects.all().order_by('-created_at')
    serializer_class = TutorialVideoSerializer
    permission_classes = [IsTeacher]
    parser_classes = [MultiPartParser, FormParser]

class TutorialVideoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TutorialVideo.objects.all()
    serializer_class = TutorialVideoSerializer
    permission_classes = [IsTeacher]

# ─── Student Views ──────────────────────────────────────────────────────────

class StudentResultsView(generics.ListAPIView):
    serializer_class = StudentResultSerializer
    permission_classes = [IsStudent]
    filter_backends = [filters.SearchFilter]
    search_fields = [
        'stream__exam__title',
        'stream__exam__teacher__first_name',
        'stream__exam__teacher__last_name',
    ]

    # ТЗ: "фильтр по дате... по баллам" — это альтернативные опции, не комбинируемые.
    # Предыдущий баг: date_order=oldest&score_order=highest игнорировал date_order полностью.
    _ORDERING_MAP = {
        'newest':  '-end_time',
        'oldest':  'end_time',
        'highest': '-score',
        'lowest':  'score',
    }

    def get_queryset(self):
        # По ТЗ: история результатов — только завершённые/аннулированные экзамены.
        # IN_PROGRESS не должен попадать в "Историю результатов".
        qs = (
            ExamAttempt.objects
            .filter(
                student=self.request.user,
                status__in=[
                    ExamAttempt.Status.COMPLETED,
                    ExamAttempt.Status.TERMINATED,
                ],
            )
            .select_related('stream__exam__teacher')
        )

        ordering_param = self.request.query_params.get('ordering', 'newest')
        order_field = self._ORDERING_MAP.get(ordering_param, '-end_time')
        return qs.order_by(order_field)


def _build_proctoring_config(
    exam: Exam,
    stream: Stream,
    attempt: ExamAttempt,
    violations_count: int | None = None,
) -> dict:
    """
    Build proctoring config dict.
    violations_count: pass 0 for new attempts to skip the DB query;
    leave None to read from attempt (triggers 1 SQL via violations_count property).
    """
    mic_status = exam.microphone_status
    if mic_status == Exam.MicrophoneStatus.OFF:
        mic_active = False
    elif mic_status == Exam.MicrophoneStatus.ON:
        mic_active = True
    else:
        mic_active = stream.mic_enabled

    if violations_count is None:
        violations_count = attempt.violations_count

    return {
        "show_mic_check": mic_active,
        "show_camera_check": exam.require_face_record,
        "record_face": exam.require_face_record,
        "record_screen": exam.require_screen_record,
        "mic_active": mic_active,
        "mic_mode": mic_status,
        "stream_mic_enabled": stream.mic_enabled,
        "max_violations": exam.max_violations,
        "current_violations": violations_count,
        "rules_accepted": attempt.rules_accepted_at is not None,
        "workplace_ready": attempt.workplace_ready_at is not None,
        "duration_seconds": exam.duration_minutes * 60,
        "remaining_seconds": attempt.remaining_seconds,
    }


class StudentExamStartView(APIView):
    permission_classes = [IsStudent]

    def get(self, request, uuid):
        # select_related — один запрос вместо lazy-load для stream.exam и exam.teacher
        stream = get_object_or_404(
            Stream.objects.select_related('exam__teacher'),
            access_link_uuid=uuid,
        )
        exam = stream.exam

        # Обрабатываем IntegrityError при двойном одновременном запросе.
        # Django get_or_create не атомарен в случаях race — unique_together зловит IntegrityError.
        created = False
        try:
            attempt, created = ExamAttempt.objects.get_or_create(
                stream=stream,
                student=request.user,
                defaults={'status': ExamAttempt.Status.IN_PROGRESS},
            )
        except IntegrityError:
            # Параллельный запрос успел создать attempt первым — получаем его
            attempt = get_object_or_404(ExamAttempt, stream=stream, student=request.user)

        if attempt.status == ExamAttempt.Status.TERMINATED:
            return Response({'detail': 'Ваш экзамен был аннулирован из-за нарушений прокторинга.'}, status=status.HTTP_403_FORBIDDEN)

        if attempt.status == ExamAttempt.Status.COMPLETED:
            return Response({'detail': 'Вы уже прошли этот экзамен.', 'attempt_id': attempt.id, 'score': attempt.score, 'grade': attempt.grade}, status=status.HTTP_200_OK)

        # FIXED: истекшее время — обновляем в транзакции с select_for_update во избежание состояния гонки
        if not created and attempt.remaining_seconds == 0:
            with transaction.atomic():
                attempt = ExamAttempt.objects.select_for_update().get(pk=attempt.pk)
                if attempt.status == ExamAttempt.Status.IN_PROGRESS:
                    attempt.status = ExamAttempt.Status.TERMINATED
                    attempt.end_time = now()
                    attempt.save(update_fields=['status', 'end_time'])
            return Response({'detail': 'Время экзамена истекло.'}, status=status.HTTP_403_FORBIDDEN)

        questions_data = []
        for q in exam.questions.prefetch_related('options').all():
            q_data = {
                'id': q.id, 'text': q.text,
                'image': request.build_absolute_uri(q.image.url) if q.image else None,
                'type': q.type, 'score': q.score, 'order': q.order,
            }
            if q.type in ['CHOICE', 'PHOTO_CHOICE']:
                q_data['options'] = [
                    {'id': opt.id, 'text': opt.text, 'image': request.build_absolute_uri(opt.image.url) if opt.image else None, 'order': opt.order}
                    for opt in q.options.all()
                ]
            elif q.type == 'INTERACTIVE':
                q_data['min_length'] = q.min_answer_length
            questions_data.append(q_data)

        return Response({
            'attempt_id': attempt.id,
            'is_new': created,
            # For new attempts pass violations_count=0 — avoids 1 SQL (we know it's empty).
            # For existing attempts pass None to let the property query the DB.
            'proctoring': _build_proctoring_config(
                exam, stream, attempt,
                violations_count=0 if created else None,
            ),
            'exam': {'id': exam.id, 'title': exam.title, 'duration_minutes': exam.duration_minutes, 'max_score': exam.max_score},
            'stream': {'id': stream.id, 'title': stream.title},
            'questions': questions_data,
        })

class StudentExamSubmitView(APIView):
    permission_classes = [IsStudent]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'exam_submit'

    def post(self, request, uuid):
        # select_related — один запрос для stream + exam + данных необходимых для валидации таймаута
        stream = get_object_or_404(
            Stream.objects.select_related('exam'),
            access_link_uuid=uuid,
        )

        with transaction.atomic():
            attempt = get_object_or_404(
                ExamAttempt.objects.select_for_update().select_related('stream__exam'),
                stream=stream,
                student=request.user,
            )

            if attempt.status != ExamAttempt.Status.IN_PROGRESS:
                return Response({'detail': 'Экзамен уже завершён или аннулирован.'}, status=status.HTTP_400_BAD_REQUEST)

            # Added Grace period of 60 seconds
            if attempt.remaining_seconds == 0 and (now() - attempt.start_time).total_seconds() > (stream.exam.duration_minutes * 60 + 60):
                attempt.status = ExamAttempt.Status.TERMINATED
                attempt.end_time = now()
                attempt.save(update_fields=['status', 'end_time'])
                return Response({'detail': 'Время экзамена истекло.'}, status=status.HTTP_400_BAD_REQUEST)

            serializer = ExamSubmitSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            answers = serializer.validated_data['answers']
            # Защита от пустого submit: студент не может сжечь попытку передав пустой список.
            if not answers:
                return Response(
                    {'detail': 'Нельзя отправить пустой список ответов.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                attempt = submit_exam_answers(attempt, answers)
            except ExamValidationError as exc:
                # Domain exception from service layer (e.g. min_answer_length violation).
                # Transaction rolls back automatically on exception leaving status=IN_PROGRESS.
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'exam_title': stream.exam.title,
            'score': attempt.score,
            'max_score': stream.exam.max_score,
            'grade': attempt.grade,
            'duration_formatted': attempt.duration_formatted,
        }, status=status.HTTP_200_OK)

class StudentUploadRecordingView(APIView):
    permission_classes = [IsStudent]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'recording_upload'

    def post(self, request, uuid):
        stream = get_object_or_404(
            Stream.objects.select_related('exam'),
            access_link_uuid=uuid,
        )
        attempt = get_object_or_404(
            ExamAttempt.objects.select_related('stream__exam'),
            stream=stream,
            student=request.user,
        )
        recording_type = request.data.get('type', 'screen')

        # Запись возможна только если экзамен не аннулирован — защита от загрузки после аннулирования
        if attempt.status == ExamAttempt.Status.TERMINATED:
            return Response(
                {'detail': 'Загрузка записей недоступна — экзамен аннулирован.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if 'file' not in request.FILES:
            return Response({'detail': 'Укажите файл в поле file.'}, status=status.HTTP_400_BAD_REQUEST)

        file_obj = request.FILES['file']

        # First check Content-Type header (fast)
        if not file_obj.content_type.startswith('video/'):
            return Response({'detail': 'Разрешены только видео-файлы.'}, status=status.HTTP_400_BAD_REQUEST)

        # FIXED SEC-3: validate actual file content via magic bytes
        if not _is_valid_video(file_obj):
            return Response({'detail': 'Файл не является валидным видео.'}, status=status.HTTP_400_BAD_REQUEST)

        if file_obj.size > 500 * 1024 * 1024:
            return Response({'detail': 'Размер файла превышает 500 МБ.'}, status=status.HTTP_400_BAD_REQUEST)

        if recording_type == 'screen':
            attempt.screen_recording = file_obj
        elif recording_type == 'face':
            attempt.face_recording = file_obj
        else:
            return Response({'detail': 'Параметр type: screen или face.'}, status=status.HTTP_400_BAD_REQUEST)

        attempt.save(update_fields=['screen_recording'] if recording_type == 'screen' else ['face_recording'])
        return Response({'detail': f'Запись ({recording_type}) загружена.'})


class ViolationCreateView(APIView):
    permission_classes = [IsStudent]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'burst'

    def post(self, request, uuid):
        # select_related — предзагружаем stream+exam чтобы избежать lazy-load в ответе
        stream = get_object_or_404(
            Stream.objects.select_related('exam'),
            access_link_uuid=uuid,
        )
        attempt = get_object_or_404(
            ExamAttempt.objects.select_related('stream__exam'),
            stream=stream,
            student=request.user,
            status=ExamAttempt.Status.IN_PROGRESS,
        )

        serializer = ViolationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        count, terminated = record_violation(attempt, serializer.validated_data['violation_type'])
        violation_type = serializer.validated_data['violation_type']

        return Response({
            'violation_type': violation_type,
            'violation_display': dict(Violation.ViolationType.choices).get(violation_type, ''),
            'violations_count': count,
            'max_violations': stream.exam.max_violations,  # уже в кэше select_related
            'terminated': terminated,
            'message': (
                'Предупреждения исчерпаны. Система завершает экзамен.'
                if terminated else f'Нарушение прокторинга! {count}'
            ),
        })


class AcceptRulesView(APIView):
    permission_classes = [IsStudent]

    def post(self, request, uuid):
        stream = get_object_or_404(Stream, access_link_uuid=uuid)
        attempt = get_object_or_404(
            ExamAttempt,
            stream=stream,
            student=request.user,
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        if not attempt.rules_accepted_at:
            attempt.rules_accepted_at = now()
            attempt.save(update_fields=['rules_accepted_at'])
        return Response(AttemptPreExamSerializer(attempt).data)


class WorkplaceReadyView(APIView):
    permission_classes = [IsStudent]

    def post(self, request, uuid):
        stream = get_object_or_404(Stream, access_link_uuid=uuid)
        attempt = get_object_or_404(
            ExamAttempt,
            stream=stream,
            student=request.user,
            status=ExamAttempt.Status.IN_PROGRESS,
        )
        if not attempt.workplace_ready_at:
            attempt.workplace_ready_at = now()
            attempt.save(update_fields=['workplace_ready_at'])
        return Response(AttemptPreExamSerializer(attempt).data)


class TutorialVideoPublicView(generics.ListAPIView):
    queryset = TutorialVideo.objects.all().order_by('-created_at')
    serializer_class = TutorialVideoSerializer
    permission_classes = [permissions.IsAuthenticated]
