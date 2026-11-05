"""Password reset by email, for people who have an email address. (People without one get a
fresh activation code from an admin instead; see activation.py.)

Asking never reveals whether an account exists. A link is a Django password-reset token: it
expires (PASSWORD_RESET_TIMEOUT) and stops working once the password changes.
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .authentication import can_sign_in
from .models import User

logger = logging.getLogger(__name__)

MAX_ACCOUNTS_PER_REQUEST = 5  # a parent's address may also be on their children's accounts

MESSAGE = """Hello {name},

Someone asked to reset the password for the YAP account "{username}" at {school}.
If it was you, choose a new password here (the link works once, for {hours} hours):

{link}

If it wasn't you, ignore this email; your password hasn't changed.
"""


def accounts_for(login):
    login = login.strip()
    if not login:
        return []
    matches = (
        User.objects.filter(Q(username__iexact=login) | Q(email__iexact=login))
        .exclude(email="")
        .select_related("school")
        .order_by("pk")[:MAX_ACCOUNTS_PER_REQUEST]
    )
    return [user for user in matches if can_sign_in(user)]


def reset_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.PASSWORD_RESET_URL}?uid={uid}&token={token}"


def send_reset_emails(login):
    for user in accounts_for(login):
        body = MESSAGE.format(
            name=user.first_name or user.username,
            username=user.username,
            school=user.school.name if user.school else "YAP",
            hours=settings.PASSWORD_RESET_TIMEOUT // 3600,
            link=reset_link(user),
        )
        try:
            send_mail("Reset your YAP password", body, None, [user.email])
        except Exception:  # never reveal delivery problems to the asker; log for staff
            logger.exception("password reset email to user %s failed", user.pk)


def user_for_token(uid, token):
    """The user a reset link belongs to, or None if the link is wrong, used or expired."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        return None
    if not can_sign_in(user) or not default_token_generator.check_token(user, token):
        return None
    return user
