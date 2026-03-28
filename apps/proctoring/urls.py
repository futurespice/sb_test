from django.urls import path

from .views import (
    StreamStudentsView, StreamStudentsPDFView,
    AttemptAnswersView, ManualGradeView,
    StudentRecordingView, TutorialVideoListView, TutorialVideoDetailView,
    StudentResultsView,
    StudentExamStartView, StudentExamSubmitView,
    StudentUploadRecordingView, ViolationCreateView,
    AcceptRulesView, WorkplaceReadyView,
    TutorialVideoPublicView
)

app_name = 'proctoring'

urlpatterns = [
    # Teacher: Stream students + PDF
    path('teacher/exams/<int:exam_pk>/streams/<int:stream_pk>/students/', StreamStudentsView.as_view(), name='stream_students'),
    path('teacher/exams/<int:exam_pk>/streams/<int:stream_pk>/students/pdf/', StreamStudentsPDFView.as_view(), name='stream_students_pdf'),

    # Teacher: Manual grading
    path('teacher/attempts/<int:attempt_pk>/answers/', AttemptAnswersView.as_view(), name='attempt_answers'),
    path('teacher/answers/<int:answer_pk>/grade/', ManualGradeView.as_view(), name='manual_grade'),

    # Teacher: Recordings / Tutorial Videos
    path('teacher/recordings/<int:attempt_pk>/', StudentRecordingView.as_view(), name='student_recording'),
    path('teacher/videos/tutorial/', TutorialVideoListView.as_view(), name='tutorial_videos'),
    path('teacher/videos/tutorial/<int:pk>/', TutorialVideoDetailView.as_view(), name='tutorial_video_detail'),

    # Student: Results History
    path('student/results/', StudentResultsView.as_view(), name='student_results'),

    # Student: Exam flow via invite link
    path('student/exam/<uuid:uuid>/', StudentExamStartView.as_view(), name='student_exam_start'),
    path('student/exam/<uuid:uuid>/accept-rules/', AcceptRulesView.as_view(), name='accept_rules'),
    path('student/exam/<uuid:uuid>/workplace-ready/', WorkplaceReadyView.as_view(), name='workplace_ready'),
    path('student/exam/<uuid:uuid>/submit/', StudentExamSubmitView.as_view(), name='student_exam_submit'),
    path('student/exam/<uuid:uuid>/upload/', StudentUploadRecordingView.as_view(), name='student_upload'),
    path('student/exam/<uuid:uuid>/violation/', ViolationCreateView.as_view(), name='student_violation'),

    # Public Tutorial Videos
    path('videos/tutorial/', TutorialVideoPublicView.as_view(), name='tutorial_public'),
]
