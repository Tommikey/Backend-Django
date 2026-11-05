"""Scheduled work, queued by ``python manage.py rqcron config.cron`` (run exactly one) and
carried out by the workers. Needs REDIS_URL."""

from rq import cron

from apps.notifications.tasks import purge_old_notifications, send_live_class_reminders

cron.register(send_live_class_reminders, "default", interval=60, job_timeout=120)
cron.register(purge_old_notifications, "default", cron="30 2 * * *", job_timeout=600)
