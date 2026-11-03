from rest_framework.routers import DefaultRouter

from .views import AssessmentViewSet, SubmissionViewSet

app_name = "assessments"

router = DefaultRouter()
router.register("assessments", AssessmentViewSet, basename="assessment")
router.register("submissions", SubmissionViewSet, basename="submission")

urlpatterns = router.urls
