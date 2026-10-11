# Partner Portal

A Django-based partner portal for managing leads, orders and commissions, support tickets, KYC documents, announcements and resources, notifications (email + in-app), recycle bin and global search, with a Progressive Web App (PWA) interface. It runs on Django 6.x, uses Bootstrap 5, a shared dark-mode-aware CSS theme (`static/css/portal.css`) and a database-backed file storage so uploads survive redeploys. Notifications and OCR run asynchronously where possible and never crash the request path.

## Features

- **Partners and staff**: role-aware access with approval gating (unapproved partners are blocked until staff approve).
- **Leads and orders**: tracking from lead to converted order; order-level commission fields.
- **Support tickets**: ticket threads with replies; status updates by staff and controlled visibility for partners.
- **Announcements and documents**: portal content with visibility rules (`visible_to`) and file-size display.
- **KYC documents with OCR**: partner uploads stored in DB, OCR suggestions generated (daemon thread after transaction commit), privacy-aware masking and status tracking.
- **Notifications**: email (Brevo HTTPS API in production, SMTP in other cases) and in-app feed; WhatsApp channel exists but is disabled by default (sandbox/template constraints).
- **Recycle bin**: soft-delete across SoftDeleteModel entities with restore/hard-delete and purge command.
- **Global search**: top-bar search (GET `/search/`) with permission-aware grouped results and type-ahead suggestions.
- **PWA**: web manifest, service worker, offline page (service worker is disabled in DEBUG in code to avoid dev caching; see `config/settings.py`/`core/views.py` and `docs/pwa.md`).

## Tech stack

- Python 3.14, Django 6.1 (see `requirements.txt`).
- Bootstrap 5 + Bootstrap Icons (CDN), Chart.js.
- PostgreSQL on Neon (production) via `DATABASE_URL` (psycopg2-binary).
- Email: Brevo API backend (`core.email_backends.BrevoAPIEmailBackend`) when `BREVO_API_KEY` set; else SMTP.
- OCR: OCR.space provider (`core.services.ocr`) with daemon post-commit processing, daily limits and size cap.
- Notifications: in-DB `NotificationLog`, dedupe/quota per channel.
- Storage: `DatabaseFileStorage` stores uploads in `core.StoredFile` (no public disk URLs).
- Frontend: shared `static/css/portal.css`, dark mode via CSS variables, responsive/mobile polish.

## Local setup (Windows PowerShell)

Prerequisites: Python 3.14 installed; repository at `F:\Partner portal` (current workspace).

```powershell
# 1. Create and activate venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment for local dev (optional .env; DEBUG defaults to True when RENDER not present)
$env:DJANGO_DEBUG = "True"
$env:DJANGO_SECRET_KEY = "dev-only-insecure-key"
# For SQLite local dev, DATABASE_URL is optional; settings use SQLite if absent.

# 4. Migrate database
python manage.py migrate

# 5. Create a superuser
python manage.py createsuperuser

# 6. Run the development server
python manage.py runserver

# 7. Run tests (full suite)
python manage.py test
```

Notes (verified in code):
- DEBUG is `True` in local (no `RENDER` env), `False` when `RENDER` is present; `DJANGO_DEBUG` can override (`config/settings.py`).
- SECRET_KEY falls back to a dev key only when DEBUG is True; in production raises `ImproperlyConfigured` if missing.
- Database: if `DATABASE_URL` exists, uses `dj_database_url` (Postgres); otherwise defaults to `db.sqlite3`.
- Static files: `collectstatic --no-input` runs in `build.sh`. Manifest strictness behavior is adjusted for tests in code (see settings); locally with DEBUG, `STATICFILES_MANIFEST_STRICT` may be false in certain contexts.
- File uploads: stored via DB storage; downloads via login-required view, not public URLs.

## Links to other docs

- `docs/ARCHITECTURE.md` — apps, models, request flow (approval middleware), notifications, OCR pipeline, storage, PWA.
- `docs/RUNBOOK.md` — Render deploy, env vars, secret rotation, rollback, tests, troubleshooting.
- `docs/BACKUP_RESTORE.md` — backup/restore procedure (Neon local PowerShell session), verification, frequency, warnings.
- `docs/CLIENT_HANDOFF.md` — decisions client must provide (hosting, domain/email auth, WhatsApp templates/number, OCR/privacy, retention/backup owner).
- `docs/pwa.md`, `docs/ocr.md`, `docs/whatsapp.md` — feature specifics.


ℹ️: any item marked "verify" in subsequent docs means the exact value/behaviour could not be fully extracted from the checked source at the time of writing and must be verified in the deployed environment/config.
