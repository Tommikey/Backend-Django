from django.urls import path

from .views import MeView, RegisterView

app_name = "accounts"

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/me/", MeView.as_view(), name="me"),
]
