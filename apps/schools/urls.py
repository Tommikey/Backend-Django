from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ComponentsView, GradeBandsView, LevelViewSet, MySchoolView, OnboardView

app_name = "schools"

router = DefaultRouter()
router.register("schools/levels", LevelViewSet, basename="level")

urlpatterns = router.urls + [
    path("schools/onboard/", OnboardView.as_view(), name="onboard"),
    path("schools/me/", MySchoolView.as_view(), name="my-school"),
    path("schools/components/", ComponentsView.as_view(), name="components"),
    path("schools/grade-bands/", GradeBandsView.as_view(), name="grade-bands"),
]
