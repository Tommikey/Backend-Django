from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ClassTimetableView, PeriodViewSet, TeacherTimetableView

app_name = "timetable"

router = DefaultRouter()
router.register("timetable/periods", PeriodViewSet, basename="period")

urlpatterns = [
    path("timetable/class/", ClassTimetableView.as_view(), name="class"),
    path("timetable/teacher/", TeacherTimetableView.as_view(), name="teacher"),
    *router.urls,
]
