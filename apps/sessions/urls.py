from rest_framework.routers import DefaultRouter

from .views import StudySessionViewSet

app_name = "sessions"

router = DefaultRouter()
router.register("sessions", StudySessionViewSet, basename="studysession")

urlpatterns = router.urls
