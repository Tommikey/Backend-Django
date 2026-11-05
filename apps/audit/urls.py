from rest_framework.routers import DefaultRouter

from .views import AuditViewSet

app_name = "audit"

router = DefaultRouter()
router.register("audit", AuditViewSet, basename="audit")

urlpatterns = router.urls
