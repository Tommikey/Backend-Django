from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import GuardianshipViewSet, LoginView, MeView, UserViewSet

app_name = "accounts"

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("guardianships", GuardianshipViewSet, basename="guardianship")

urlpatterns = router.urls + [
    path("auth/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/me/", MeView.as_view(), name="me"),
]
