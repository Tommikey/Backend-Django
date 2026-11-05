"""
Django settings for the YAP school backend. All secrets/env come from .env.
"""

from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# unsafe-for-production values are opt-in: local development turns them on in .env
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOW_ALL_ORIGINS=(bool, False),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECURE_SSL_REDIRECT=(bool, True),
    SECURE_HSTS_SECONDS=(int, 60 * 60 * 24 * 30),
    LOG_LEVEL=(str, "INFO"),
    NUM_PROXIES=(int, 0),
    EMAIL_URL=(str, "consolemail://"),
    DEFAULT_FROM_EMAIL=(str, "YAP <no-reply@localhost>"),
    PASSWORD_RESET_URL=(str, "http://localhost:3000/reset-password"),
    FILE_STORAGE=(str, "local"),
    S3_ENDPOINT_URL=(str, ""),
    S3_REGION=(str, ""),
    S3_ADDRESSING_STYLE=(str, "auto"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    # local
    "apps.schools",
    "apps.accounts",
    "apps.academics",
    "apps.assessments",
    "apps.live_classes",
    "apps.results",
    "apps.attendance",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Django admin assets under gunicorn
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db_url("DATABASE_URL")}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("apps.accounts.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.accounts.pagination.Pagination",
    # ?search= and ?ordering= on lists; each viewset names its search_fields / ordering_fields
    "DEFAULT_FILTER_BACKENDS": (
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "login": "60/min",  # per IP: generous, a school lab often shares one IP
        "login_user": "10/min",  # per username: password guessing
        "onboard": "10/hour",  # per IP: new schools
        "password": "10/hour",  # per user: guessing the current password with a stolen token
        "reset_login": "3/hour",  # per username/email: reset emails to one person
        "reset_ip": "30/hour",  # per IP: reset emails overall
    },
    # proxies in front of the app (1 behind a load balancer), so client IPs come from the
    # right X-Forwarded-For entry; 0 trusts only the socket address
    "NUM_PROXIES": env("NUM_PROXIES"),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # login and refresh: active user of an active school (see apps/accounts/authentication.py)
    "USER_AUTHENTICATION_RULE": "apps.accounts.authentication.can_sign_in",
    # each refresh hands out a new refresh token and retires the old one (logout = blacklist)
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # tokens carry a hash of the password: changing it ends every existing session
    "CHECK_REVOKE_TOKEN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "YAP School Platform API",
    "DESCRIPTION": (
        "Multi-school API: school setup, the school year, lessons, assessments, live classes, "
        "attendance and term results. Authenticate with `POST /api/v1/auth/token/` and send "
        "`Authorization: Bearer <access>`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,  # separate request/response shapes (write-only fields)
    "SCHEMA_PATH_PREFIX": r"/api/v1",
}

# email: e.g. smtp+tls://user:password@smtp.example.com:587 (console in development)
vars().update(env.email_url("EMAIL_URL"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
# the frontend page that finishes a password reset; ?uid=&token= are appended
PASSWORD_RESET_URL = env("PASSWORD_RESET_URL")
PASSWORD_RESET_TIMEOUT = 60 * 60 * 3  # reset links work for 3 hours

CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")  # e.g. https://app.yap.school
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")  # the Django admin's https origin

if not DEBUG:
    # deployed behind a TLS-terminating proxy that sets X-Forwarded-Proto
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # load balancers probe over plain HTTP
    SECURE_HSTS_SECONDS = env("SECURE_HSTS_SECONDS")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# HSTS preload is a one-way commitment for the whole domain; decide it per deployment
SILENCED_SYSTEM_CHECKS = ["security.W021"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL")},
    "loggers": {"django.request": {"level": "WARNING"}},  # 4xx/5xx with tracebacks
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"  # never served publicly: downloads go through access-checked endpoints
MEDIA_ROOT = BASE_DIR / "media"

# uploaded files: "local" (MEDIA_ROOT, streamed by the API) or "s3" (a private bucket on AWS S3,
# Cloudflare R2, MinIO...; downloads redirect to links that expire in minutes)
FILE_STORAGE = env("FILE_STORAGE")
if FILE_STORAGE == "s3":
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET"),
            "access_key": env("S3_ACCESS_KEY_ID"),
            "secret_key": env("S3_SECRET_ACCESS_KEY"),
            "endpoint_url": env("S3_ENDPOINT_URL") or None,  # blank: AWS itself
            "region_name": env("S3_REGION") or None,
            "addressing_style": env("S3_ADDRESSING_STYLE"),  # "path" for MinIO
            "default_acl": "private",
            "querystring_auth": True,
            # SigV4 links: the legacy SigV2 default is refused by R2 and newer AWS regions
            "signature_version": "s3v4",
            "file_overwrite": False,
        },
    }
elif FILE_STORAGE != "local":
    raise ImproperlyConfigured("FILE_STORAGE must be 'local' or 's3'.")
FILES_SERVED_BY_REDIRECT = FILE_STORAGE == "s3"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
