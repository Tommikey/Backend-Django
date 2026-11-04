from django.urls import path

from .views import ClassSummaryView, RegisterView, StudentAttendanceView

app_name = "attendance"

urlpatterns = [
    path("attendance/register/", RegisterView.as_view(), name="register"),
    path("attendance/summary/", ClassSummaryView.as_view(), name="summary"),
    path("attendance/student/", StudentAttendanceView.as_view(), name="student"),
]
