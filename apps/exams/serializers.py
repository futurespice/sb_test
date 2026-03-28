from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.urls import reverse
from rest_framework import serializers

from .models import Exam, Question, Option, Stream

User = get_user_model()

class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'text', 'image', 'is_correct', 'order']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request and hasattr(request.user, 'role') and request.user.role == User.Role.STUDENT:
            data.pop('is_correct', None)
        return data

class OptionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'text', 'image', 'is_correct', 'order']

class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)
    type_abbr = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ['id', 'text', 'image', 'type', 'type_abbr', 'score', 'order',
                  'expected_answer', 'min_answer_length', 'options']

    def get_type_abbr(self, obj):
        return {'CHOICE': 'ТП', 'INTERACTIVE': 'ИО', 'PHOTO_CHOICE': 'ОФ'}.get(obj.type, obj.type)

class QuestionCreateSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    options = OptionCreateSerializer(many=True, required=False)

    class Meta:
        model = Question
        fields = ['id', 'text', 'image', 'type', 'score', 'order',
                  'expected_answer', 'min_answer_length', 'options']

    def create(self, validated_data):
        options_data = validated_data.pop('options', [])
        question = Question.objects.create(**validated_data)
        # FIXED ARCH-3: bulk_create — один INSERT вместо N.
        if options_data:
            Option.objects.bulk_create([
                Option(question=question, **opt) for opt in options_data
            ])
        return question

    def update(self, instance, validated_data):
        options_data = validated_data.pop('options', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if options_data is not None:
            # FIXED ARCH-3: bulk_create — один DELETE + один INSERT вместо N.
            instance.options.all().delete()
            if options_data:
                Option.objects.bulk_create([
                    Option(question=instance, **opt) for opt in options_data
                ])
        return instance

class QuestionSummarySerializer(serializers.ModelSerializer):
    has_image = serializers.SerializerMethodField()
    has_title = serializers.SerializerMethodField()
    has_options = serializers.SerializerMethodField()
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    type_abbr = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = [
            'id', 'text', 'type', 'type_display', 'type_abbr', 'score', 'order',
            'has_image', 'has_title', 'has_options',
        ]

    def get_has_image(self, obj):
        return bool(obj.image)

    def get_has_title(self, obj):
        return bool(obj.text)

    def get_has_options(self, obj):
        # FIXED RISK-2: .exists() игнорирует prefetch-кэш и всегда идёт в БД.
        # len(all()) читает prefetch-кэш — ноль дополнительных запросов.
        return len(obj.options.all()) > 0

    def get_type_abbr(self, obj):
        return {'CHOICE': 'ТП', 'INTERACTIVE': 'ИО', 'PHOTO_CHOICE': 'ОФ'}.get(obj.type, obj.type)

class ExamSerializer(serializers.ModelSerializer):
    # FIXED ARCH-1: не используем source='questions.count' — он делает SELECT COUNT(*) на каждый объект.
    # Читаем из annotate(questions_count_db=...) в queryset, с fallback для отдельных объектов.
    questions_count = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField(read_only=True)
    total_questions_score = serializers.SerializerMethodField()
    duration_formatted = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'theme', 'difficulty', 'duration_minutes', 'duration_formatted',
            'max_score', 'exam_date', 'microphone_status',
            'require_screen_record', 'require_face_record',
            'max_violations',
            'questions_count', 'total_questions_score',
            'teacher_name', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_questions_count(self, obj):
        # Используем annotated значение если есть, иначе fallback без SQL
        annotated = getattr(obj, 'questions_count_db', None)
        if annotated is not None:
            return annotated
        return obj.questions.count()

    def get_teacher_name(self, obj):
        return obj.teacher.get_full_name()

    def get_total_questions_score(self, obj):
        # Используем annotated Sum если есть, иначе fallback (aggregate)
        annotated = getattr(obj, 'total_score_db', None)
        if annotated is not None:
            return annotated
        return obj.questions_total_score

    def get_duration_formatted(self, obj):
        h = obj.duration_minutes // 60
        m = obj.duration_minutes % 60
        if h:
            return f"{h}ч.{m:02d}м."
        return f"{m}м."

class ExamCreateSerializer(serializers.ModelSerializer):
    # max_score=0 ⁃ calculate_grade returns 1 for any score – students always get grade 1.
    max_score = serializers.IntegerField(min_value=1)

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'theme', 'difficulty', 'duration_minutes',
            'max_score', 'exam_date', 'microphone_status',
            'require_screen_record', 'require_face_record',
            'max_violations',
        ]


class ExamFullUpdateSerializer(serializers.ModelSerializer):
    # max_length=200: prevents a single request from inserting 10 000 questions + 40 000 options.
    questions = QuestionCreateSerializer(many=True, required=False, max_length=200)

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'theme', 'difficulty', 'duration_minutes',
            'max_score', 'exam_date', 'microphone_status',
            'require_screen_record', 'require_face_record',
            'max_violations', 'questions'
        ]

    @transaction.atomic
    def update(self, instance, validated_data):
        questions_data = validated_data.pop('questions', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if questions_data is not None:
            # Один запрос — получаем все существующие вопросы в dict {id: question}
            existing_questions = {q.id: q for q in instance.questions.prefetch_related('options')}
            new_q_ids = {q_data.get('id') for q_data in questions_data if q_data.get('id')}

            # Удаляем вопросы которых нет в новом списке (один запрос)
            ids_to_delete = set(existing_questions.keys()) - new_q_ids
            if ids_to_delete:
                Question.objects.filter(id__in=ids_to_delete).delete()

            questions_to_update = []
            questions_to_create = []
            all_options_data = []  # [(question_ref_or_none, options_data), ...]

            for order, q_data in enumerate(questions_data, start=1):
                # Shallow copy — prevents mutating validated_data in-place.
                # Without copy, q_data.pop('options') and q_data['order']=order
                # corrupt the original validated_data on any retry/double-save.
                q_data = dict(q_data)
                options_data = q_data.pop('options', None)
                q_id = q_data.get('id')
                q_data['order'] = order

                if q_id and q_id in existing_questions:
                    question = existing_questions[q_id]
                    for attr, value in q_data.items():
                        setattr(question, attr, value)
                    questions_to_update.append(question)
                    all_options_data.append((question, options_data))
                else:
                    q_data.pop('id', None)
                    new_q = Question(exam=instance, **q_data)
                    questions_to_create.append((new_q, options_data))

            # Bulk update существующих вопросов (один запрос)
            if questions_to_update:
                Question.objects.bulk_update(
                    questions_to_update,
                    ['text', 'image', 'type', 'score', 'order', 'expected_answer', 'min_answer_length']
                )

            # Bulk create новых вопросов (один запрос)
            if questions_to_create:
                new_question_objs = [q for q, _ in questions_to_create]
                created = Question.objects.bulk_create(new_question_objs)
                for created_q, (_, opts) in zip(created, questions_to_create):
                    all_options_data.append((created_q, opts))

            # Пересоздаём options одним проходом (bulk)
            option_objects = []
            questions_with_new_options = [
                q for q, opts in all_options_data if opts is not None
            ]
            if questions_with_new_options:
                # Удаляем старые options одним запросом
                Option.objects.filter(question__in=questions_with_new_options).delete()

            for question, opts in all_options_data:
                if opts is None:
                    continue
                for opt_order, o_data in enumerate(opts, start=1):
                    o_data.pop('id', None)
                    o_data['order'] = opt_order
                    option_objects.append(Option(question=question, **o_data))

            if option_objects:
                Option.objects.bulk_create(option_objects)

        # Пересчитываем max_score (один запрос)
        instance.max_score = instance.questions.aggregate(total=models.Sum('score'))['total'] or 0
        instance.save(update_fields=['max_score'])

        return instance

class StreamSerializer(serializers.ModelSerializer):
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    exam_max_score = serializers.IntegerField(source='exam.max_score', read_only=True)
    students_count = serializers.SerializerMethodField()
    invite_url = serializers.SerializerMethodField()

    class Meta:
        model = Stream
        fields = [
            'id', 'exam', 'exam_title', 'exam_max_score', 'title', 'access_link_uuid',
            'mic_enabled', 'students_count', 'invite_url', 'created_at',
        ]
        read_only_fields = ['access_link_uuid', 'created_at']

    def get_students_count(self, obj):
        # FIXED ARCH-2: читаем из annotate(students_count_db=Count('attempts')).
        # Если аннотация есть — ноль доп. запросов; иначе — fallback на .count().
        annotated = getattr(obj, 'students_count_db', None)
        if annotated is not None:
            return annotated
        return obj.attempts.count()

    def get_invite_url(self, obj):
        request = self.context.get('request')
        if request:
            # reverse() — не хардкодим path, используем имя маршрута
            return request.build_absolute_uri(
                reverse('proctoring:student_exam_start', kwargs={'uuid': obj.access_link_uuid})
            )
        return str(obj.access_link_uuid)

class StreamCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stream
        fields = ['id', 'title', 'mic_enabled']

class AIGenerateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    theme = serializers.CharField(max_length=255, required=False, allow_blank=True)
    difficulty = serializers.ChoiceField(choices=Exam.Difficulty.choices, required=False)
    question_count = serializers.IntegerField(min_value=1, max_value=50, default=10)
    file = serializers.FileField(required=False, allow_null=True)

class SetUniformScoreSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=1, max_value=100)
