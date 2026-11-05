# YAP — School Platform Backend

The REST API behind YAP, a multi-school platform for running a school year online: classes and
timetabled teaching, lessons, quizzes and assignments, live classes, and term results with
report cards.

One deployment serves many schools. Each school picks its education system when it signs up —
**Nigerian (JSS/SSS)**, **British (Year 7–13)** or **US (Grade 6–12)** — and gets sensible defaults
for that system (levels, term names, score split, grade scale), which its admin can then edit.
Nothing in the code branches on the system; the differences are all data.

Built with Django 5.2, Django REST Framework, JWT auth (SimpleJWT) and PostgreSQL.

## What it does

| Area | What's there |
| --- | --- |
| **Schools** | Public onboarding (school + first admin in one call), school settings, class levels, a score split per session (e.g. CA1 20 + CA2 20 + Exam 60, must add up to 100), grade scale |
| **People** | Students, teachers, parents and admins, all scoped to one school. Admins link parents to their children, or import everyone from a CSV |
| **School year** | Academic sessions with their terms, subjects, class arms (JSS1A) with a form teacher, who teaches what to which class, which class each student is in, and moving everyone into the next session |
| **Learning** | Lessons per class, subject and term, with completion tracking and progress reports |
| **Assessments** | Quizzes (auto-graded multiple choice) and assignments (graded by the teacher), with submissions |
| **Live classes** | Scheduled online sessions for a class and subject, with a join link |
| **Attendance** | A daily class register taken by the form teacher (present, late, absent, excused), term summaries per class and per student, attendance printed on report cards |
| **Results** | Score sheets per class and subject, form teacher and principal comments, class broadsheet, publishing a term into fixed report cards (with positions or GPA where the school uses them) |

### Who sees what

- **Admins** run their school: people, the school year, settings, and publishing results.
- **Teachers** work on the classes and subjects they're assigned: lessons, assessments, live
  classes and scores. A class's **form teacher** also sees that class's broadsheet and writes its
  report card comments, and takes its daily register.
- **Students** see their own classes and who teaches them, their work, attendance and published
  report cards.
- **Parents** see what their linked children see, read-only: lessons, assessments (without
  answer keys), the children's submissions and grades, live classes, classes and teachers, plus
  attendance and published report cards. `?child=<id>` narrows a list to one child.
- **Schools are isolated.** Another school's data behaves as if it doesn't exist; IDs from other
  schools are rejected as unknown, not forbidden.
- **Platform staff** (superusers) use the Django admin only and belong to no school. They can
  suspend a school (`is_active`), which signs out all of its users at once.
- **Records are kept.** People with school records (classes, marks, attendance, work) can't be
  deleted, only deactivated, and a role can't change after an account is created.

### Results in brief

Teachers enter marks per component on a score sheet. Until the term is published, admins and the
form teacher can preview live draft report cards. Publishing snapshots every report card — totals,
grades, class averages, positions or GPA, and the grade scale in force — and locks scores and
comments, so a published card never changes if the school edits its settings later. An admin can
unpublish a term to make corrections. Publishing runs as a background job (see
[Background jobs](#background-jobs)).

### Attendance in brief

The form teacher (or an admin) takes the class register once per school day, marking each student
present, late, absent or excused, with an optional note. A day counts as a day the school opened for
that class once its register has been taken. Late counts as present, and excused absences are counted
separately from other absences. Report cards print the term's attendance. Publishing snapshots it and
locks the register along with the scores, and unpublishing reopens both.

## Getting started

Requirements: Python 3.13 and Docker (for PostgreSQL).

```bash
# 1. Database (PostgreSQL 17 on localhost:5433)
docker compose up -d

# 2. Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 3. Settings
cp .env.example .env          # then set SECRET_KEY

# 4. Schema and demo data
python manage.py migrate
python manage.py seed         # safe to re-run

# 5. Run
python manage.py runserver
```

The API is at `http://localhost:8000/api/v1/`, its interactive docs at
`http://localhost:8000/api/docs/` (OpenAPI schema at `/api/schema/`), and the Django admin at
`http://localhost:8000/admin/`.

### Demo accounts

`seed` creates three demo schools, one per system, each with a running school year, classes,
lessons, assessments, a live class, two weeks of attendance and term scores (not yet published).
Students have admission numbers made from the school's initials (`DSS/2025/001` and so on). Every password is
`pass1234`.

| School | System | Usernames |
| --- | --- | --- |
| Demo Secondary School | Nigerian | `admin`, `teacher1`, `teacher2`, `student1`–`student5`, `parent1` |
| Demo Academy | British | the same names with a `uk_` prefix |
| Demo High School | US | the same names with a `us_` prefix |

`platform` is a superuser for the Django admin.

## Using the API

Every endpoint except onboarding and login needs a JWT:

```bash
curl -X POST localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "pass1234"}'
# -> {"access": "...", "refresh": "..."}

curl localhost:8000/api/v1/auth/me/ -H 'Authorization: Bearer <access>'
```

Access tokens last 1 hour. Refresh them at `POST /api/v1/auth/token/refresh/`, which also returns
a new refresh token (the old one stops working). `POST auth/logout/` with `{"refresh": ...}` ends a
device's session. `POST auth/password/` with `current_password` and `new_password` changes your
own password and returns fresh tokens. Any password change, including an admin reset, signs the
person out everywhere else.

### Background jobs

Slow work runs outside the request. `POST results/publish/` answers `202` with a job and a
`Location` header; poll `GET jobs/{id}/` until `status` is `done` (the outcome is in `result`)
or `failed` (a message for the user is in `error`). `GET jobs/` lists them (`?kind=`,
`?status=`): admins see the school's, everyone else their own. Password-reset emails are queued
too, and retried if the mail server is down.

With `REDIS_URL` set, jobs wait in Redis until a worker runs them:

```bash
python manage.py rqworker default --with-scheduler
```

Without it (the default for development and tests) the same jobs run straight away inside the
request, so the answer is already `done`. Platform staff can watch the queue at `/admin/rq/`.

Timed work (live class reminders every minute, nightly cleanup) is queued by one scheduler
process, configured in `config/cron.py`:

```bash
python manage.py rqcron config.cron
```

### Notifications

People are told, in the app and by email when they have an address:

| Event | Who |
|---|---|
| A term's results are published | Each student with a report card, and their parents |
| A student is marked absent (today's or yesterday's register) | Their parents |
| A quiz or assignment is set | The class's students |
| A live class starts within 15 minutes | The class's students |

`GET notifications/` lists yours, newest first (`?unread=true`, `?kind=`); each has `data` with
the ids to open what it is about. `POST notifications/{id}/read/`, `POST notifications/read-all/`,
`GET notifications/unread-count/` (also `unread_notifications` in `auth/me/`).
`GET/PATCH notifications/settings/` turns the emails off. Emails go out from the worker in
batches; read notifications are deleted after 90 days, any after a year.

### Audit log

Admins can see who changed what at `GET audit/`, newest first: each entry has the action, who did
it (name kept even if the account goes), when, from which IP, what it was about, and the
changes as before -> after. Recorded:

- marks (one entry per score-sheet save, one row per changed mark), the register, report card
  comments, grading, publishing and unpublishing results;
- people: created, edited (a password reset shows only that it happened), deactivated,
  deleted, activation codes issued, passwords changed or reset, first sign-in; imports;
- parent links, enrollments (class moves), teaching assignments, classes and form teachers,
  rollovers;
- school settings, the score split and the grade scale.

Filter with `?action=` (`scores` or `scores.updated`), `?actor=`, `?student=` (everything
about one student), `?classroom=`, `?term=`, `?target_type=&target_id=`, `?since=&until=`
(dates). Entries can't be edited or deleted, through the API or the Django admin.

Times in notifications, and "today" for registers and dashboards, are in the school's time zone
(`timezone` in `schools/me/`, set from the system's preset: Africa/Lagos, Europe/London,
America/New_York).

### Score splits

Each session has its own split of a subject's score (`schools/components/`, `?session=` to pick
one; the current session by default). A new session starts with a copy of the latest session's
split, so changing next year's never touches this year's marks; a split locks once scores are
entered against it. Report cards print the split their term used.

### Moving to a new session

At the end of a school year the admin creates the next session, then calls
`POST academics/rollover/` with `to_session`. It previews by default: each student is promoted to
the same arm one level up (JSS1A → JSS2A, or the only class in that level), and students in the
final level graduate. The preview shows each student's latest published average and any terms
not yet published. Decisions override the defaults per student: `repeat`, `move` (to a named
class), `graduate` or `leave`. With `commit=true` the new enrollments are created at once, along
with this session's teaching assignments (`copy_teaching_assignments`, on by default);
`make_current=true` also switches the school to the new session. Each student's outcome
(promoted, repeated, moved, graduated, left) is recorded on their old enrollment. Graduates and
leavers keep their accounts, so their report cards stay readable. Running it again skips everyone
already handled, unless a decision names them (a returning student, say).

### Bringing people in

Admins import students, teachers and parents from a CSV at `POST imports/people/` (template at
`GET imports/people/template/`). The import previews by default, listing every problem by
spreadsheet row; with `commit=true` it creates everyone at once, enrolls students in their class
and links parents to their children. Blank usernames are made from names (`ada.obi`).

Imported people have no password yet. Each gets a one-time **activation code** (e.g. `K7M2-QX9P`,
valid 30 days), returned once for printing on login slips. On first sign-in they send their
username, the code and a password of their choice to `POST auth/activate/`. An admin can issue a
fresh code at `POST users/{id}/activation-code/`, which also serves as a password reset for
people without email. People with an email address can reset their own password:
`POST auth/password-reset/` emails a link to `PASSWORD_RESET_URL`, and the frontend finishes it
at `POST auth/password-reset/confirm/`.

`GET auth/me/` returns your profile plus everything a client needs to start: the school's
settings, the current session and term, and your working context (a teacher's classes, a
student's class, a parent's children). `GET dashboard/` returns what your role should see first:
missing registers, work to grade or due, upcoming live classes, attendance, the latest report card.

List endpoints are paginated (50 per page; `?page_size=` up to 200) and most take `?search=`
and `?ordering=` (see the docs for each list's fields). Endpoints that work on a term default to the school's
current term when `term` is left out. Login is limited to 10 attempts a minute per username, and
school sign-up to 10 an hour per IP; going over returns `429`.

All routes are under `/api/v1/`:

| Area | Routes |
| --- | --- |
| Auth | `auth/token/`, `auth/token/refresh/`, `auth/logout/`, `auth/password/`, `auth/activate/`, `auth/password-reset/`, `auth/password-reset/confirm/`, `auth/me/` |
| Dashboard | `dashboard/` |
| Schools | `schools/onboard/`, `schools/me/`, `schools/levels/`, `schools/components/`, `schools/grade-bands/` |
| People | `users/`, `users/{id}/activation-code/`, `guardianships/`, `imports/people/`, `imports/people/template/` |
| School year | `academics/academic-sessions/`, `academics/terms/`, `academics/subjects/`, `academics/classrooms/`, `academics/teaching-assignments/`, `academics/enrollments/`, `academics/rollover/` |
| Learning | `academics/lessons/`, `academics/progress/`, `stats/` |
| Assessments | `assessments/`, `submissions/` |
| Live classes | `live-classes/` |
| Results | `results/score-sheet/`, `results/comments/`, `results/class-results/`, `results/report-card/`, `results/publish/`, `results/unpublish/` |
| Attendance | `attendance/register/`, `attendance/summary/`, `attendance/student/` |
| Jobs | `jobs/` |
| Notifications | `notifications/`, `notifications/settings/` |
| Audit log | `audit/` |

## Project layout

```
config/            settings, root URLs, health check
apps/
  schools/         schools (tenants), onboarding, per-system presets, levels, score split, grade scale
  accounts/        custom User with roles, parent links, shared access-control mixins, seed command
  academics/       sessions, terms, subjects, classes, teaching assignments, enrollments, lessons, progress
  assessments/     quizzes, assignments, submissions, grading
  live_classes/    scheduled online classes
  results/         scores, comments, results maths, publishing, report cards
  attendance/      daily class register, term attendance counts
  dashboard/       what each role sees first
  jobs/            background jobs (django-rq) and their status
  notifications/   in-app and email notifications, live class reminders
  audit/           who changed what: marks, attendance, people, settings
conftest.py        shared pytest fixtures
```

## Development

```bash
pytest                  # full test suite (needs the database running)
ruff check .            # lint
ruff format .           # format
```

Configuration comes from `.env` (see `.env.example`). Never commit `.env`.

| Setting | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | (required) | Long and random in production |
| `DATABASE_URL` | (required) | |
| `DEBUG` | `False` | Turn on for local development only |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | |
| `CORS_ALLOWED_ORIGINS` | empty | The frontend's origin(s), e.g. `https://app.example.com` |
| `CORS_ALLOW_ALL_ORIGINS` | `False` | Local development only |
| `CSRF_TRUSTED_ORIGINS` | empty | The Django admin's `https://` origin |
| `SECURE_SSL_REDIRECT` | `True` | With `DEBUG=False`: redirect HTTP to HTTPS |
| `SECURE_HSTS_SECONDS` | 30 days | With `DEBUG=False` |
| `NUM_PROXIES` | `0` | Proxies in front of the app (e.g. `1` behind a load balancer), so rate limits see real client IPs |
| `LOG_LEVEL` | `INFO` | Logs go to stdout |
| `EMAIL_URL` | `consolemail://` | Outgoing email, e.g. `smtp+tls://user:password@smtp.example.com:587`; the default prints emails to the console |
| `DEFAULT_FROM_EMAIL` | `YAP <no-reply@localhost>` | |
| `FILE_STORAGE` | `local` | `local` (files in `MEDIA_ROOT`) or `s3` (a private bucket) |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | | With `FILE_STORAGE=s3` |
| `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ADDRESSING_STYLE` | AWS defaults | For R2 or MinIO set the endpoint; MinIO usually needs `path` |
| `REDIS_URL` | empty | e.g. `redis://localhost:6379/0`: background jobs go to a worker, and rate limits are shared by every process. Empty: jobs run in the request |
| `PASSWORD_RESET_URL` | `http://localhost:3000/reset-password` | The frontend page that finishes a reset; `?uid=&token=` are appended |

### Deploying with Docker

Before the first production deploy (or starting the frontend), work through
[docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md): settings to fill in, and decisions still open.

```bash
cp .env.prod.example .env.prod        # fill in secrets, hosts and origins
docker compose -f docker-compose.prod.yml up -d --build
```

This runs Postgres and Redis, applies migrations once, then starts the API under gunicorn on port
8000 (`WEB_CONCURRENCY` workers) as a non-root user, a background worker and the scheduler. Uploaded files live
in the `media` volume. `GET /healthz/` answers 200 when the app can reach its database (503
otherwise), with `"status": "degraded"` if Redis is unreachable; it needs no
login and isn't redirected to HTTPS, so load balancers can probe it. Their probes must still use
a host listed in `ALLOWED_HOSTS`.

### Production notes

- Run behind a proxy that terminates TLS and sets `X-Forwarded-Proto`. Run
  `python manage.py collectstatic` at build time; WhiteNoise serves the admin's assets.
- Rate limits are counted in Django's cache, which is Redis when `REDIS_URL` is set. Without
  it the cache is per process, so with several gunicorn workers the limits are approximate.
- Keep at least one worker running whenever `REDIS_URL` is set, or publishing never finishes and
  reset emails never leave. A job left queued or running for 15 minutes stops blocking a retry.
- If Redis goes down the API stays up: rate limits pause, and publishing fails at once with
  "try again in a few minutes". `/healthz/` reports `degraded` rather than failing, since every
  app server shares the one Redis; alert on it.
- Uploaded files (lesson materials, submissions) are private. They are stored under random
  names and downloaded only through `academics/lessons/{id}/file/` and `submissions/{id}/file/`,
  which apply the same visibility rules as the lesson or submission; a response's `file` field is
  that link. With `FILE_STORAGE=local` (default) files live in `MEDIA_ROOT` (the `media` volume)
  and the API streams them; with `FILE_STORAGE=s3` they live in a private bucket (AWS S3,
  Cloudflare R2, MinIO) and the API redirects to a link that expires in 5 minutes. Replaced and
  deleted files are removed from storage.
- CI runs `manage.py check --deploy`, fails on any API docs warning, and builds the Docker image.

## License

MIT — see [LICENSE](LICENSE).
