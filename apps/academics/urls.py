from django.urls import path
from rest_framework.routers import DefaultRouter

from .stats import StatsView
from .views import (
    ClassroomViewSet,
    EnrollmentViewSet,
    LessonViewSet,
    ProgressView,
    SubjectViewSet,
)

app_name = "academics"

router = DefaultRouter()
router.register("academics/subjects", SubjectViewSet, basename="subject")
router.register("academics/classrooms", ClassroomViewSet, basename="classroom")
router.register("academics/enrollments", EnrollmentViewSet, basename="enrollment")
router.register("academics/lessons", LessonViewSet, basename="lesson")

urlpatterns = router.urls + [
    path("academics/progress/", ProgressView.as_view(), name="progress"),
    path("stats/", StatsView.as_view(), name="stats"),
]
