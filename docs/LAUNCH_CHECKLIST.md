# Launch checklist

Work through this before the first production deploy and before building the frontend. Tick items
off in the PR that handles them, and add new ones as they come up.

## Before production

### Settings to fill in (`.env.prod`, see `.env.prod.example`)

- [ ] **`SECRET_KEY`**: long and random, stored in a secret manager. Changing it later signs
      everyone out and **invalidates every unused activation code and password-reset link**, since
      they are keyed to it.
- [ ] **`EMAIL_URL`** and **`DEFAULT_FROM_EMAIL`**: a real mail provider (the default prints emails to
      the console). Set up SPF/DKIM for the sending domain, or reset emails will land in spam.
- [ ] **`PASSWORD_RESET_URL`**: the frontend page that finishes a reset (it receives `?uid=&token=`).
- [ ] **`ALLOWED_HOSTS`**, **`CORS_ALLOWED_ORIGINS`** (the frontend), **`CSRF_TRUSTED_ORIGINS`** (the
      Django admin), **`NUM_PROXIES`** (`1` behind a load balancer).
- [ ] The load balancer's health check (`/healthz/`) uses a host listed in `ALLOWED_HOSTS`.

### Infrastructure

- [ ] **Redis and a worker**: set `REDIS_URL` and run `rqworker default --with-scheduler`
      (both are in `docker-compose.prod.yml`). Without Redis, publishing runs inside the request
      (a very large school can hit the 30 s gunicorn timeout) and rate limits are per process.
      Redis keeps queued jobs on disk (`--appendonly yes`); with a managed Redis, turn on
      persistence too. Alert on a growing queue or failed jobs (`/admin/rq/`).
- [ ] **Exactly one scheduler** (`rqcron config.cron`, the `cron` service): none means no live
      class reminders; two means every reminder is queued twice. Workers can scale freely.
- [ ] **Each school's time zone**: set from its system (Nigeria: Africa/Lagos). Check it for
      schools outside those zones; it decides "today" for registers and times in notifications.
- [ ] **Where uploaded files live**: downloads are access-checked either way. `FILE_STORAGE=local`
      keeps them in the `media` volume (one server only, and the volume must be backed up);
      `FILE_STORAGE=s3` uses a private bucket (`S3_*` settings), needed once there is more than
      one app server. Keep the bucket private: never enable public access on it.
- [ ] **Backups**: automated daily backups of the database and of uploaded files (the `media`
      volume or the bucket), and one restore actually tested.
- [ ] **Error monitoring**: decide on one (e.g. Sentry) so 500s reach someone.
- [ ] **HSTS preload**: decide. The deploy check for it is silenced, since preload is a one-way
      commitment for the whole domain.
- [ ] Create the platform superuser (`createsuperuser`) for the Django admin.

## Before the frontend

### Open decisions

- [ ] **Re-importing people**: imports only create people today; a username or admission number
      that already exists is a row error. Decide whether re-uploading a corrected spreadsheet should
      update existing students, matched by admission number.
- [ ] **API docs visibility**: `/api/docs/` and `/api/schema/` are public. Keep them public, or
      require a login.
- [ ] **Signing in with an admission number**: sign-in is by username, which is unique across all
      schools; admission numbers are only unique within one. Signing in with one would need the
      school too (e.g. a school code on the login page). Decide if students should have that.
- [ ] **Registers**: one register a day, taken by the form teacher. Decide whether schools need
      morning/afternoon registers, or registers per lesson taken by subject teachers.
- [ ] **SMS or WhatsApp for parents**: notifications are in-app and email only. Many parents
      may not read email; decide whether absences and report cards should also go by SMS or
      WhatsApp (a paid provider, e.g. Termii or Twilio), and who pays for it.
- [ ] **Who hears about new work**: today only students. Decide whether parents should too (it
      could be a lot of email), perhaps as a weekly digest instead.
- [ ] **Email for teachers and parents**: optional today. Decide whether imports should require it
      for staff, so they can reset their own passwords.

### Things the frontend must handle

- [ ] **Login slips**: activation codes are returned **once**, by the import and by
      `POST users/{id}/activation-code/`. The import screen has to offer printing or downloading
      them straight away; a lost code can only be reissued, not looked up.
- [ ] **First sign-in**: imported people have no password; their first screen is
      `POST auth/activate/` (username, code, new password), which also signs them in.
- [ ] **Password reset page** at `PASSWORD_RESET_URL`: read `uid` and `token` from the query
      string and send them with the new password to `POST auth/password-reset/confirm/`.
- [ ] **Sessions**: access tokens last an hour, refresh tokens a week. Each refresh returns a new
      refresh token and retires the old one; on a 401, refresh once and retry. Log out with
      `POST auth/logout/`. A password change returns fresh tokens for this device.
- [ ] **Startup**: `GET auth/me/` gives the shell (school settings, current term, classes or
      children); `GET dashboard/` gives each role's home screen.
- [ ] **Send JSON**: with form posts, DRF treats a missing boolean as `false`. `is_active` is
      protected, but other booleans in a full `PUT` are not.
- [ ] **Publishing is a job**: `POST results/publish/` returns `202` and a job; poll
      `jobs/{id}/` (every second or two) and show progress until `done` or `failed`.
- [ ] **Notifications**: show the bell count from `auth/me/` (`unread_notifications`), refresh it
      with `notifications/unread-count/`, open each notification's subject from its `data`, and
      give everyone the email on/off switch (`notifications/settings/`).
- [ ] Generate a typed client from `/api/schema/` rather than hand-writing request shapes.
- [ ] Lists: `?search=`, `?ordering=`, `?page_size=` (at most 200).

## Already decided

These are settled; listed so they aren't reopened by accident.

- Imported people get **activation codes, not passwords**. Hashing passwords would cost ~0.7 s
  per person and time out a whole-school import; codes take seconds for 1,000 people.
- **Admission numbers** are optional, students only, and unique per school ignoring case. They
  appear next to every student's name and can identify children in imports.
- **People with records are deactivated, not deleted**; roles are fixed once an account exists.
- **Late work is accepted** and flagged `is_late`; the teacher decides.
- Teachers see quizzes, and their answer keys, **only for what they teach or their form class**.
- **Published results lock** scores, comments and the attendance register until unpublished.
- **Parents see their children's work read-only**, live class join links included, and never act
  for them (no submitting or completing lessons).
- **Each session has its own score split**, copied from the previous one; it locks once scores
  are entered against it. The grade scale stays school-wide, since each published report card
  keeps a copy of the one it was graded with.
