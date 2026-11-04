"""Teach the API schema generator about our JWT authentication (a SimpleJWT subclass)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class SchoolJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.JWTAuthentication"
    name = "jwtAuth"
