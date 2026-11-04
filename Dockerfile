# YAP API: gunicorn behind a TLS-terminating proxy.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# static files are collected into the image; the values here exist only for this step
RUN SECRET_KEY=collectstatic-only DATABASE_URL=sqlite:////tmp/unused.db \
    python manage.py collectstatic --noinput \
 && useradd --create-home --uid 10001 yap \
 && mkdir -p /app/media \
 && chown -R yap:yap /app/media

USER yap
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4)"

# workers: gunicorn reads WEB_CONCURRENCY (default 2 here)
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-2} --access-logfile - --forwarded-allow-ips='*'"]
