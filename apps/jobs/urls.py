from rest_framework.routers import DefaultRouter

from .views import JobViewSet

app_name = "jobs"

router = DefaultRouter()
router.register("jobs", JobViewSet, basename="job")

urlpatterns = router.urls
