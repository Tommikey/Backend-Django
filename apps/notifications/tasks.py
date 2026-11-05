"""Scheduled tasks (registered in config/cron.py, run by ``manage.py rqcron config.cron``)."""

from .events import live_class_reminders
from .services import purge_old


def send_live_class_reminders():
    return live_class_reminders()


def purge_old_notifications():
    purge_old()
