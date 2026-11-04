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
| **Schools** | Public onboarding (school + first admin in one call), school settings, class levels, score split (e.g. CA1 20 + CA2 20 + Exam 60, must add up to 100), grade scale |
| **People** | Students, teachers, parents and admins, all scoped to one school. Admins link parents to their children |
| **School year** | Academic sessions with their terms, subjects, class arms (JSS1A) with a form teacher, who teaches what to which class, which class each student is in |
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
- **Students** see their own classes, work, attendance and published report cards.
- **Parents** see their linked children, their attendance and their published report cards.
- **Schools are isolated.** Another school's data behaves as if it doesn't exist; IDs from other
  schools are rejected as unknown, not forbidden.
- **Platform staff** (superusers) use the Django admin only and belong to no school.

### Results in brief

Teachers enter marks per component on a score sheet. Until the term is published, admins and the
form teacher can preview live draft report cards. Publishing snapshots every report card — totals,
grades, class averages, positions or GPA, and the grade scale in force — and locks scores and
comments, so a published card never changes if the school edits its settings later. An admin can
unpublish a term to make corrections.

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

The API is at `http://localhost:8000/api/v1/` and the Django admin at `http://localhost:8000/admin/`.

### Demo accounts

`seed` creates three demo schools, one per system, each with a running school year, classes,
lessons, assessments, a live class, two weeks of attendance and term scores (not yet published). Every password is
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

Access tokens last 1 hour; refresh them at `POST /api/v1/auth/token/refresh/`. List endpoints are
paginated (50 per page). Endpoints that work on a term default to the school's current term when
`term` is left out.

All routes are under `/api/v1/`:

| Area | Routes |
| --- | --- |
| Auth | `auth/token/`, `auth/token/refresh/`, `auth/me/` |
| Schools | `schools/onboard/`, `schools/me/`, `schools/levels/`, `schools/components/`, `schools/grade-bands/` |
| People | `users/`, `guardianships/` |
| School year | `academics/academic-sessions/`, `academics/terms/`, `academics/subjects/`, `academics/classrooms/`, `academics/teaching-assignments/`, `academics/enrollments/` |
| Learning | `academics/lessons/`, `academics/progress/`, `stats/` |
| Assessments | `assessments/`, `submissions/` |
| Live classes | `live-classes/` |
| Results | `results/score-sheet/`, `results/comments/`, `results/class-results/`, `results/report-card/`, `results/publish/`, `results/unpublish/` |
| Attendance | `attendance/register/`, `attendance/summary/`, `attendance/student/` |

## Project layout

```
config/            settings, root URLs
apps/
  schools/         schools (tenants), onboarding, per-system presets, levels, score split, grade scale
  accounts/        custom User with roles, parent links, shared access-control mixins, seed command
  academics/       sessions, terms, subjects, classes, teaching assignments, enrollments, lessons, progress
  assessments/     quizzes, assignments, submissions, grading
  live_classes/    scheduled online classes
  results/         scores, comments, results maths, publishing, report cards
  attendance/      daily class register, term attendance counts
conftest.py        shared pytest fixtures
```

## Development

```bash
pytest                  # full test suite (needs the database running)
ruff check .            # lint
ruff format .           # format
```

Configuration comes from `.env` (see `.env.example`): `SECRET_KEY`, `DEBUG`, `DATABASE_URL`,
`ALLOWED_HOSTS` and `CORS_ALLOW_ALL_ORIGINS`. Never commit `.env`.

## License

MIT — see [LICENSE](LICENSE).
