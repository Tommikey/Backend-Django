from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ActivateView,
    GuardianshipViewSet,
    ImportPeopleView,
    ImportTemplateView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    UserViewSet,
)

app_name = "accounts"

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("guardianships", GuardianshipViewSet, basename="guardianship")

urlpatterns = router.urls + [
    path("auth/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/activate/", ActivateView.as_view(), name="activate"),
    path("imports/people/", ImportPeopleView.as_view(), name="import-people"),
    path("imports/people/template/", ImportTemplateView.as_view(), name="import-template"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/password/", PasswordChangeView.as_view(), name="password"),
    path("auth/password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "auth/password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("auth/me/", MeView.as_view(), name="me"),
]
