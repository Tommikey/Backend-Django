from rest_framework.throttling import SimpleRateThrottle


class LoginUsernameThrottle(SimpleRateThrottle):
    """Login attempts per username, whatever the IP: stops password guessing on one account.

    The per-IP limit (scope ``login``) is kept generous because a whole school's computer lab
    often shares one public IP.
    """

    scope = "login_user"

    def get_cache_key(self, request, view):
        username = request.data.get("username")
        if not isinstance(username, str) or not username.strip():
            return None  # malformed request: the serializer rejects it
        return self.cache_format % {"scope": self.scope, "ident": username.strip().lower()}


class ResetLoginThrottle(SimpleRateThrottle):
    """Reset emails per username or email address, so nobody's inbox can be flooded."""

    scope = "reset_login"

    def get_cache_key(self, request, view):
        login = request.data.get("login")
        if not isinstance(login, str) or not login.strip():
            return None
        return self.cache_format % {"scope": self.scope, "ident": login.strip().lower()}
