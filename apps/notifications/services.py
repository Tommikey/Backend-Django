"""Creating notifications and emailing them.

``notify`` stores the in-app notifications in one statement and queues their emails in batches
(apps/jobs/queue.py), so a school-wide event costs a handful of queries and the emails go out
from the worker.
"""

from datetime import timedelta
from itertools import batched

from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from apps.accounts.authentication import can_sign_in
from apps.jobs.queue import EMAIL_RETRY, run_later

from .models import Notification

EMAIL_BATCH = 100
KEEP_READ = timedelta(days=90)
KEEP_ANY = timedelta(days=365)

FOOTER = """
--
{school} on YAP. To stop these emails, turn off email notifications in your settings."""


def wants_email(user):
    return bool(user.email) and user.email_notifications and user.is_active


def notify(kind, school, messages):
    """``messages``: (recipient, title, body, data) tuples. Returns the notifications."""
    rows = Notification.objects.bulk_create(
        Notification(
            school=school, recipient=recipient, kind=kind, title=title[:200], body=body, data=data
        )
        for recipient, title, body, data in messages
    )
    emailed = [row.pk for row in rows if wants_email(row.recipient)]
    for batch in batched(emailed, EMAIL_BATCH, strict=False):
        run_later(send_emails, list(batch), retry=EMAIL_RETRY)
    return rows


def send_emails(notification_ids):
    """Email these notifications over one connection. The ones sent are marked even when a
    later one fails, so the retry doesn't send them twice."""
    pending = Notification.objects.filter(
        pk__in=notification_ids, emailed_at__isnull=True
    ).select_related("recipient__school", "school")
    sent = []
    try:
        with get_connection() as connection:
            for note in pending:
                user = note.recipient
                if not wants_email(user) or not can_sign_in(user):
                    continue
                EmailMessage(
                    subject=note.title,
                    body=note.body + FOOTER.format(school=note.school.name),
                    to=[user.email],
                    connection=connection,
                ).send()
                sent.append(note.pk)
    finally:
        if sent:
            Notification.objects.filter(pk__in=sent).update(emailed_at=timezone.now())


def purge_old():
    """Daily: drop read notifications after 90 days and any after a year."""
    now = timezone.now()
    Notification.objects.filter(read_at__isnull=False, created_at__lt=now - KEEP_READ).delete()
    Notification.objects.filter(created_at__lt=now - KEEP_ANY).delete()
