"""Health check for a worker container: passes while a worker on this host is registered in
Redis. A worker re-registers on every heartbeat, so a hung or dead one drops out within
minutes (RQ's worker_ttl)."""

import socket

import django_rq
from django.core.management.base import BaseCommand, CommandError
from rq import Worker


class Command(BaseCommand):
    help = "Exit 0 if an RQ worker on this host is alive, 1 otherwise."

    def handle(self, *args, **options):
        here = socket.gethostname()
        workers = Worker.all(connection=django_rq.get_connection("default"))
        alive = [w.name for w in workers if w.hostname == here]
        if not alive:
            raise CommandError(f"no live worker on {here}")
        self.stdout.write(f"ok: {', '.join(alive)}")
