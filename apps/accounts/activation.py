"""Activation codes: how imported people (and students without email) set their own password.

A code is 8 characters from an alphabet without look-alikes (0/O, 1/I/L), shown as XXXX-XXXX:
about 40 bits, single use, expiring, and guessed only through the rate-limited activation
endpoint. Being random, it is stored as an HMAC (keyed with SECRET_KEY) rather than with the
deliberately slow password hasher, which is what lets an import issue a thousand in seconds.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ActivationCode

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
VALID_FOR = timedelta(days=30)


def new_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalise(code):
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def code_hash(user_id, code):
    message = f"{user_id}:{normalise(code)}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


@transaction.atomic
def issue_codes(users, issued_by):
    """Give each user a fresh code (replacing any earlier one). Returns {user_id: (code,
    expires_at)}; the codes exist only in this return value."""
    expires_at = timezone.now() + VALID_FOR
    codes = {user.pk: new_code() for user in users}
    ActivationCode.objects.filter(user_id__in=codes).delete()
    ActivationCode.objects.bulk_create(
        ActivationCode(
            user_id=user_id,
            code_hash=code_hash(user_id, code),
            expires_at=expires_at,
            created_by=issued_by,
        )
        for user_id, code in codes.items()
    )
    return {user_id: (code, expires_at) for user_id, code in codes.items()}


def check_code(user, code):
    """True if ``code`` is ``user``'s current, unexpired activation code."""
    record = ActivationCode.objects.filter(user=user, expires_at__gt=timezone.now()).first()
    return record is not None and hmac.compare_digest(record.code_hash, code_hash(user.pk, code))
