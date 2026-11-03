from django.apps import AppConfig


class SessionsConfig(AppConfig):
    name = "apps.sessions"
    label = "study_sessions"  # avoids colliding with django.contrib.sessions
