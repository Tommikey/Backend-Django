"""Health check for a worker or cron container: passes while a worker (or, with --cron, the
cron scheduler) on this host is registered in Redis. Both re-register on every heartbeat, so a
hung or dead process drops out within minutes."""

import socket

import django_rq
from django.core.management.base import BaseCommand, CommandError
from rq import Worker
from rq.cron import CronScheduler


class Command(BaseCommand):
    help = "Exit 0 if an RQ worker (or the cron scheduler) on this host is alive, 1 otherwise."

    def add_arguments(self, parser):
        parser.add_argument("--cron", action="store_true", help="check the cron scheduler")

    def handle(self, *args, **options):
        here = socket.gethostname()
        connection = django_rq.get_connection("default")
        kind, found = (
            ("cron scheduler", CronScheduler.all(connection))
            if options["cron"]
            else ("worker", Worker.all(connection=connection))
        )
        alive = [p.name for p in found if p.hostname == here]
        if not alive:
            raise CommandError(f"no live {kind} on {here}")
        self.stdout.write(f"ok: {', '.join(alive)}")
