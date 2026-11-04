from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ActivateView,
    GuardianshipViewSet,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    UserViewSet,
)

app_name = "accounts"

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("guardianships", GuardianshipViewSet, basename="guardianship")

urlpatterns = router.urls + [
    path("auth/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/activate/", ActivateView.as_view(), name="activate"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/password/", PasswordChangeView.as_view(), name="password"),
    path("auth/me/", MeView.as_view(), name="me"),
]
