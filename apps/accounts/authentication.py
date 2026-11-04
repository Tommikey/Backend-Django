"""Who may hold a session: an active user of an active school.

The same rule runs at login, at token refresh (SimpleJWT's ``USER_AUTHENTICATION_RULE``) and
on every request (``JWTAuthentication``), so suspending a school (``School.is_active``) or
deactivating a user locks them out at once, not when their access token expires.
"""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication as BaseJWTAuthentication


def can_sign_in(user):
    if user is None or not user.is_active:
        return False
    # platform staff have no school; everyone else needs theirs to be active
    return user.school_id is None or user.school.is_active


class JWTAuthentication(BaseJWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not can_sign_in(user):
            raise AuthenticationFailed("This account or its school is not active.", code="inactive")
        return user
