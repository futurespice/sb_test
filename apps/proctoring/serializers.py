from rest_framework import serializers
from .models import ExamAttempt, AnswerAttempt, Violation, TutorialVideo
from apps.exams.models import Question

class AttemptStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='student.email', read_only=True)
    exam_title = serializers.CharField(source='stream.exam.title', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    duration_seconds = serializers.IntegerField(read_only=True)
    duration_formatted = serializers.SerializerMethodField()
    violations_count = serializers.IntegerField(read_only=True)
    end_date = serializers.SerializerMethodField()
    has_screen_recording = serializers.SerializerMethodField()
    has_face_recording = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            'id', 'student_name', 'student_email', 'exam_title', 'teacher_name',
            'score', 'grade', 'status', 'duration_seconds', 'duration_formatted',
            'violations_count', 'start_time', 'end_time', 'end_date',
            # Не возвращаем raw FileField (путь к файлу без ауторизации).
            # URL-записи доступны только через StudentRecordingView (проверяет stream__exam__teacher).
            'has_screen_recording', 'has_face_recording',
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_teacher_name(self, obj):
        return obj.stream.exam.teacher.get_full_name()

    def get_duration_formatted(self, obj):
        return obj.duration_formatted

    def get_end_date(self, obj):
        return obj.end_time.strftime('%d.%m.%Y') if obj.end_time else '—'

    def get_has_screen_recording(self, obj):
        return bool(obj.screen_recording)

    def get_has_face_recording(self, obj):
        return bool(obj.face_recording)

class StudentResultSerializer(serializers.ModelSerializer):
    exam_title = serializers.CharField(source='stream.exam.title', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    duration_seconds = serializers.IntegerField(read_only=True)
    duration_formatted = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            'id', 'exam_title', 'teacher_name', 'score', 'grade',
            'status', 'duration_seconds', 'duration_formatted',
            'start_time', 'end_time', 'date',
        ]

    def get_teacher_name(self, obj):
        return obj.stream.exam.teacher.get_full_name()

    def get_duration_formatted(self, obj):
        return obj.duration_formatted

    def get_date(self, obj):
        if obj.end_time:
            return obj.end_time.strftime('%d.%m.%Y')
        if obj.start_time:
            return obj.start_time.strftime('%d.%m.%Y')
        return '—'

class AnswerSubmitSerializer(serializers.Serializer):
    question = serializers.IntegerField(min_value=1)
    selected_option = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    # max_length ограничивает payload: защита от DoS через огромный text_answer
    text_answer = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=10_000
    )


class ExamSubmitSerializer(serializers.Serializer):
    answers = AnswerSubmitSerializer(many=True, max_length=200)

    def validate_answers(self, value: list) -> list:
        """Duplicate question_id in one submit would inflate score via bulk_create."""
        q_ids = [a['question'] for a in value]
        if len(q_ids) != len(set(q_ids)):
            raise serializers.ValidationError(
                'В списке ответов есть дублирующиеся вопросы.'
            )
        return value

class AnswerAttemptSerializer(serializers.ModelSerializer):
    question_text = serializers.CharField(source='question.text', read_only=True)
    question_type = serializers.CharField(source='question.type', read_only=True)
    question_max_score = serializers.IntegerField(source='question.score', read_only=True)

    class Meta:
        model = AnswerAttempt
        fields = [
            'id', 'question', 'question_text', 'question_type', 'question_max_score',
            'selected_option', 'text_answer', 'score_earned', 'is_manually_graded',
        ]
        read_only_fields = ['question', 'selected_option', 'text_answer', 'is_manually_graded']

class ManualGradeSerializer(serializers.Serializer):
    score_earned = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if self.instance:
            max_q_score = self.instance.question.score
            if attrs['score_earned'] > max_q_score:
                raise serializers.ValidationError(
                    {'score_earned': f'Балл не может превышать {max_q_score}.'}
                )
        return attrs

class ViolationSerializer(serializers.ModelSerializer):
    violation_display = serializers.CharField(source='get_violation_type_display', read_only=True)

    class Meta:
        model = Violation
        fields = ['id', 'violation_type', 'violation_display', 'created_at']

class ViolationCreateSerializer(serializers.Serializer):
    violation_type = serializers.ChoiceField(choices=Violation.ViolationType.choices)

class TutorialVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutorialVideo
        fields = ['id', 'title', 'description', 'video_file', 'created_at']

class AttemptPreExamSerializer(serializers.ModelSerializer):
    rules_accepted = serializers.SerializerMethodField()
    workplace_ready = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = ['id', 'rules_accepted', 'rules_accepted_at', 'workplace_ready', 'workplace_ready_at']

    def get_rules_accepted(self, obj):
        return obj.rules_accepted_at is not None

    def get_workplace_ready(self, obj):
        return obj.workplace_ready_at is not None
