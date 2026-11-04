from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/", include("apps.schools.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.academics.urls")),
    path("api/v1/", include("apps.assessments.urls")),
    path("api/v1/", include("apps.live_classes.urls")),
    path("api/v1/", include("apps.results.urls")),
    path("api/v1/", include("apps.attendance.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
