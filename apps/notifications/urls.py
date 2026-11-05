from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationSettingsView, NotificationViewSet

app_name = "notifications"

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    # before the router, whose detail route would otherwise take "settings" for an id
    path("notifications/settings/", NotificationSettingsView.as_view(), name="settings"),
    *router.urls,
]
