from rest_framework.routers import DefaultRouter

from .views import LiveClassViewSet

app_name = "live_classes"

router = DefaultRouter()
router.register("live-classes", LiveClassViewSet, basename="live-class")

urlpatterns = router.urls
