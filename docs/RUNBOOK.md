# Runbook

## Deploy flow (Render)

This project is configured for Render (build.sh + render setup implied by settings):
- `build.sh`: runs `pip install -r requirements.txt`, `python manage.py collectstatic --no-input`, `python manage.py migrate`, and auto-creates superuser via `createsuperuser --noinput` if `DJANGO_SUPERUSER_*` env vars are set.
- Render runs `build.sh` during build; migrations run at build time (not just release). Auto-deploy from `main` branch (verify in Render dashboard).
- Ephemeral filesystem on free tier: uploaded files (stored in DB via DatabaseFileStorage) persist in DB rows but any local disk writes outside DB storage are lost on restart/redeploy. Staticfiles collected to `staticfiles/` at build time.
- Free web service sleeps after inactivity (first request after sleep can be slow). Free Render Postgres may expire (see CLIENT_HANDOFF).

## Required environment variables (production)

From verified code (`config/settings.py`, `build.sh`):

| Name | Required (prod) | What it does |
|---|---|---|
| `DJANGO_SECRET_KEY` (or `SECRET_KEY`) | **Yes** (when DEBUG False) | Django secret key. If missing and not DEBUG → `ImproperlyConfigured`. |
| `DJANGO_DEBUG` | Optional | Overrides DEBUG. "true/1/yes/t" → True. Defaults: DEBUG=False if `RENDER` present, else True. |
| `RENDER` | Optional (set by Render) | Triggers production defaults (DEBUG False) and can help derive `SITE_URL`/hosts. |
| `ALLOWED_HOSTS` | Optional | Comma-separated hostnames. `RENDER_EXTERNAL_HOSTNAME` added automatically. |
| `CSRF_TRUSTED_ORIGINS` | Optional | Comma-separated origins (https://...). Render hostname origin added. |
| `DATABASE_URL` | Yes (prod) | Postgres URL (psycopg2-binary). If absent, uses SQLite locally. |
| `DB_DISABLE_SERVER_SIDE_CURSORS` | Optional | Set `True` to force client-side cursors globally. Recommended on Neon (especially behind a pooler) to avoid dropped named cursors during `dumpdata` / `queryset.iterator()`. Default `False`. |
| `DEFAULT_FROM_EMAIL` | Optional | Sender for notifications/password reset emails. |
| `BREVO_API_KEY` | Yes if using Brevo email | Enables Brevo HTTPS API backend (`core.email_backends.BrevoAPIEmailBackend`). If unset in non-DEBUG, SMTP backend selected by logic. |
| `EMAIL_HOST/PORT/USE_TLS/USE_SSL/USER/PASS` | Optional | SMTP config when not using Brevo. |
| `SITE_URL` | Optional | Absolute base URL without trailing slash for notification emails. If empty and `RENDER_EXTERNAL_HOSTNAME` set, derived as `https://<host>`. |
| `NOTIFY_EMAIL_DAILY_LIMIT` | Optional | Email daily cap (default 200). |
| `WHATSAPP_ENABLED` | Optional | "true" enables WhatsApp channel (disabled by default). |
| `WHATSAPP_PROVIDER` | Optional | Default `twilio`. |
| `TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM` | Required if WHATSAPP_ENABLED | Twilio WhatsApp credentials/from number. |
| `WHATSAPP_ALLOWED_NUMBERS` | Optional | Comma-separated E.164 numbers allowed to receive. |
| `NOTIFY_WHATSAPP_DAILY_LIMIT` | Optional | WhatsApp daily cap (default 50; <=0 means unlimited in code path — verify). |
| `OCR_ENABLED` | Optional | "true" enables OCR processing. |
| `OCR_PROVIDER` | Optional | Default `ocrspace`. |
| `OCRSPACE_API_KEY` | Required if OCR_ENABLED | OCR.space API key. |
| `OCR_DAILY_LIMIT` | Optional | Daily cap (default 100). |
| `OCR_MAX_BYTES` | Optional | Max bytes per file (default 1048576 = 1MB). |
| `SECURE_HSTS_SECONDS` | Optional | HSTS max-age in non-DEBUG (default 3600). |
| `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` | Optional | Used by `build.sh` to create superuser on build (createsuperuser --noinput). |

## How to rotate secrets

- **Django SECRET_KEY**: generate new random key; update Render env var `DJANGO_SECRET_KEY` (or `SECRET_KEY`). Redeploy. Active sessions may be invalidated (signed cookies).
- **Database password**: rotate in Neon (or Postgres provider). Update `DATABASE_URL` in Render (password embedded). Redeploy and verify connectivity.
- **Brevo API key**: generate new key in Brevo; update `BREVO_API_KEY`. Test with `python manage.py send_test_email <recipient>`. Revoke old key.
- **OCR.space API key**: rotate in OCR.space account; update `OCRSPACE_API_KEY`. Test OCR flow on a small document (with OCR_ENABLED true).
- **Twilio (if enabled)**: rotate Auth Token in Twilio Console; update `TWILIO_AUTH_TOKEN`. Also rotate Account SID only if required; update `TWILIO_ACCOUNT_SID`. Test WhatsApp send via `send_test_whatsapp`.

## Roll back a bad deploy

1. In Render, go to the service → Deploys → find last known-good commit → "Redeploy" that commit (or promote previous build).
2. If DB schema changed in bad deploy, restoring from a known-good backup may be required (see BACKUP_RESTORE). Only restore into empty DB or with care (migrations state).
3. Verify: `python manage.py check`, smoke test login/dashboard, key flows.

## Create the first superuser

- Locally: `python manage.py createsuperuser`.
- On Render: set `DJANGO_SUPERUSER_*` env vars and let `build.sh` run (createsuperuser --noinput; command ignores if user exists).

## Tests: how to run and duration

- All tests: `python manage.py test` (Django test runner). Suite includes unit/integration and CSS/backup tests added.
- Specific: `python manage.py test core.tests_backup`, `python manage.py test core.tests_ui_css`, `python manage.py test core.tests_global_search`.
- Duration (verified in recent runs): full suite ~5s (305 tests) including notifications/ocr tests with mocked network. Duration may vary slightly by environment; mark as "verify" for Render exact timing.

## Common errors and causes

| Error | Cause / Fix |
|---|---|
| `ImproperlyConfigured: DJANGO_SECRET_KEY environment variable must be set in production.` | `SECRET_KEY`/`DJANGO_SECRET_KEY` missing when DEBUG False (RENDER present). Set secret in Render env. |
| CSRF failures (403 on POST) | Missing/incorrect `CSRF_TRUSTED_ORIGINS` or HTTPS behind proxy without proper headers. Ensure Render origin added (code auto-adds `RENDER_EXTERNAL_HOSTNAME`), and `SECURE_PROXY_SSL_HEADER` set when not DEBUG. |
| `'no such table'` after pulling new migrations locally | Run `python manage.py migrate`. If DB out of sync, consider recreating local DB or migrating. |
| File missing after redeploy (uploads) | Files uploaded to disk will be lost on ephemeral filesystem. This app uses `DatabaseFileStorage` (uploads stored in DB) so DB-backed uploads survive redeploys; ensure using DB storage paths (default for partner documents per code). |
| Brevo API rejected (401/403) | Invalid/rotated `BREVO_API_KEY`. Test with `send_test_email`. |
| OCR.space errors / quota | `OCR_ENABLED` true but key missing/invalid, or `OCR_DAILY_LIMIT` reached, or file > `OCR_MAX_BYTES`. Check logs and limits. |
| WhatsApp sandbox restrictions | Free Twilio sandbox only accepts pre-registered templates and numbers in sandbox; production requires approved templates/number. Channel disabled by default. |
| Approval redirect loops | Unapproved partner accessing allowed paths? Check middleware exempt prefixes; `/search/` not exempt (intentional). Ensure `approval_pending` route accessible. |
| Static manifest errors in tests/dev | Manifest strictness behavior adjusted in test contexts; in local dev run `collectstatic` after adding assets if using manifest storage. |
| Notifications not sent but no exception | Wrapped in `transaction.on_commit` and deduped; may be suppressed by dedupe/quota or transaction rolled back. Check `NotificationLog`. |
| `CommandError: Unable to serialize database: cursor "_django_curs_..." does not exist` | Neon/Postgres dropped a server-side (named) cursor, e.g. compute suspended or a pooler in front. `backup_data` disables server-side cursors for the dump automatically; to protect the whole app set `DB_DISABLE_SERVER_SIDE_CURSORS=True` in the environment. See `docs/BACKUP_RESTORE.md`. |

## Pre-deploy checklist

- [ ] Env vars set correctly in Render (secrets not committed).
- [ ] `build.sh` succeeds (collectstatic + migrate + superuser creation as configured).
- [ ] `python manage.py check` passes.
- [ ] Tests pass locally (`python manage.py test`).
- [ ] Database migrations reviewed (`makemigrations --check --dry-run` clean).
- [ ] Backups in place / backup command tested (optional but recommended).
- [ ] PWA endpoints configured/working (`manifest.webmanifest`, `service-worker.js`, `/offline/`).
- [ ] Email/WhatsApp/OCR toggles match intended environment (disabled by default).
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` include Render hostname.
- [ ] No secrets printed in logs (verified code redacts).