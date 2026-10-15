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
| `DEFAULT_FROM_EMAIL` | Optional | Fallback sender for notifications/password reset emails. |
| `BREVO_SENDER_EMAIL` | Recommended with Brevo | Verified Brevo sender. When set it overrides every per-message From, preventing `400 sender not valid`. |
| `BREVO_SENDER_NAME` | Optional | Display name for `BREVO_SENDER_EMAIL`. |
| `BREVO_API_KEY` | Yes if using Brevo email | Enables Brevo HTTPS API backend (`core.email_backends.BrevoAPIEmailBackend`). If unset in non-DEBUG, SMTP backend selected by logic. |
| `EMAIL_PROVIDER` | Optional | `brevo`, `gmail_api` or `console`. Empty keeps the default: Brevo when `BREVO_API_KEY` is set, otherwise console (DEBUG) / SMTP. Any other value raises `ImproperlyConfigured` at startup. |
| `GMAIL_CLIENT_ID` | Yes if `EMAIL_PROVIDER=gmail_api` | Desktop OAuth client ID from Google Cloud. |
| `GMAIL_CLIENT_SECRET` | Yes if `EMAIL_PROVIDER=gmail_api` | Desktop OAuth client secret. Keep secret. |
| `GMAIL_REFRESH_TOKEN` | Yes if `EMAIL_PROVIDER=gmail_api` | Refresh token from `scripts/get_gmail_refresh_token.py`. Keep secret. |
| `GMAIL_SENDER` | Yes if `EMAIL_PROVIDER=gmail_api` | The Gmail address that authorised the token. `DEFAULT_FROM_EMAIL` becomes `Partner Portal <GMAIL_SENDER>`. |
| `EMAIL_HOST/PORT/USE_TLS/USE_SSL/USER/PASS` | Optional | SMTP config when not using Brevo. |
| `SITE_URL` | Optional | Absolute base URL without trailing slash for notification emails. If empty and `RENDER_EXTERNAL_HOSTNAME` set, derived as `https://<host>`. |
| `NOTIFY_EMAIL_DAILY_LIMIT` | Optional | Email daily cap (default 200). |
| `WHATSAPP_ENABLED` | Optional | "true" enables WhatsApp channel (disabled by default). |
| `WHATSAPP_PROVIDER` | Optional | Default `twilio`; set `360dialog` for the 360dialog provider (Phase 5). |
| `TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_WHATSAPP_FROM` | Required if provider=twilio | Twilio WhatsApp credentials/from number. |
| `D360_API_KEY` | Required if provider=360dialog | 360dialog API key (`D360-API-KEY` header). |
| `D360_BASE_URL` | Optional | 360dialog base URL (default `https://waba-sandbox.360dialog.io`). |
| `D360_WEBHOOK_TOKEN` | Required for inbound | Shared secret in the inbound webhook URL path. |
| `WHATSAPP_ALLOWED_NUMBERS` | Optional | Comma-separated E.164 numbers allowed to receive. |
| `NOTIFY_WHATSAPP_DAILY_LIMIT` | Optional | WhatsApp daily cap (default 50; <=0 means unlimited in code path — verify). |
| `OCR_ENABLED` | Optional | "true" enables OCR processing. |
| `OCR_PROVIDER` | Optional | `ocrspace` (default), `tesseract` (engine on the server, needs the Docker deploy) or `hybrid` (Tesseract first, OCR.space fallback). See `docs/ocr.md`. |
| `OCRSPACE_API_KEY` | Required for `ocrspace`; optional for `hybrid` | OCR.space API key. |
| `OCR_DAILY_LIMIT` | Optional | OCR.space calls per day (default 100). Tesseract runs are not counted. |
| `OCR_MAX_BYTES` | Optional | Max bytes per file sent to OCR.space (default 1048576 = 1MB). |
| `OCR_TESSERACT_LANG` | Optional | Tesseract languages (default `eng+hin`). |
| `OCR_TESSERACT_TIMEOUT` | Optional | Seconds per Tesseract/pdftoppm step (default 120). |
| `OCR_PDF_MAX_PAGES` | Optional | PDF pages read by Tesseract (default 5). |
| `SECURE_HSTS_SECONDS` | Optional | HSTS max-age in non-DEBUG (default 3600). |
| `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` | Optional | Used by `build.sh` to create superuser on build (createsuperuser --noinput). |

## Email through the Gmail API (EMAIL_PROVIDER=gmail_api)

Render's free tier blocks SMTP, so when Brevo is unavailable the portal can send through the Gmail REST API over HTTPS (`core.email_backends.GmailAPIEmailBackend`). It uses an OAuth refresh token, refreshes the short-lived access token automatically and caches it in memory until about 60 seconds before it expires. It never logs secrets or tokens.

> **Warning: publish the OAuth app.** While the OAuth consent screen's publishing status is **Testing**, Google expires refresh tokens after **7 days**, and email stops with `invalid_grant`. Set the app to **In production** *before* you generate the refresh token. You do not need Google verification for personal use. You will see a "Google hasn't verified this app" warning during consent, which is acceptable: click **Advanced → Go to … (unsafe)**.

> **Sender address.** The Gmail API always sends **from the Gmail account that authorised the refresh token**. The From display name is "Partner Portal", but the address is that Gmail account. This is a stop-gap. For a client deployment, switch to an authenticated custom domain (SPF/DKIM/DMARC) with Brevo or Resend.

### 1. Create the Google Cloud project and enable the Gmail API

1. Sign in to <https://console.cloud.google.com/> with the Gmail account that will send the mail.
2. Open the project picker and click **New project**. Name it (for example `partner-portal-mail`) and click **Create**, then select it.
3. Go to **APIs & Services → Library**, search for **Gmail API**, open it and click **Enable**.

### 2. Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen** (shown as **Google Auth Platform → Branding / Audience** in newer consoles).
2. Choose User type **External**. Fill in the app name (`Partner Portal`), the user support email and the developer contact email, then save.
3. Under **Data access / Scopes**, add `https://www.googleapis.com/auth/gmail.send`. That is the only scope needed.
4. Under **Audience**, click **Publish app** and confirm, so the status is **In production**. See the warning above: in Testing, the token dies after 7 days.

### 3. Create a Desktop OAuth client

1. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID** (or **Clients → Create client**).
2. Application type: **Desktop app**. Name: `partner-portal-local`. Click **Create**.
3. Copy the **Client ID** and **Client secret**. Do not commit them or put them in a file in the repo.

### 4. Obtain the refresh token (locally)

In PowerShell, from the project root with the venv active:

```powershell
$env:GMAIL_CLIENT_ID = "<client id>"
$env:GMAIL_CLIENT_SECRET = "<client secret>"
python scripts/get_gmail_refresh_token.py
```

The script opens the Google consent page in your browser and listens on a loopback address (`http://127.0.0.1:<random port>/`). Sign in with the sending Gmail account and approve the `gmail.send` permission. The terminal prints **only the refresh token**, and nothing is written to disk. If Google returns no refresh token, remove the app at <https://myaccount.google.com/permissions> and run the script again. Close the terminal afterwards so the env vars are cleared.

### 5. Set the Render environment variables

In Render → the web service → **Environment**:

| Name | Value |
|---|---|
| `EMAIL_PROVIDER` | `gmail_api` |
| `GMAIL_CLIENT_ID` | the Desktop client ID |
| `GMAIL_CLIENT_SECRET` | the Desktop client secret |
| `GMAIL_REFRESH_TOKEN` | the token printed in step 4 |
| `GMAIL_SENDER` | the Gmail address that approved the consent, for example `yourname@gmail.com` |

`BREVO_API_KEY` can stay set: `EMAIL_PROVIDER=gmail_api` takes precedence. `DEFAULT_FROM_EMAIL` is overridden with `Partner Portal <GMAIL_SENDER>`. Save and let Render redeploy, then open the service **Shell** and run:

```bash
python manage.py send_test_email you@example.com
```

It prints the backend, the From address, and then either `Success` or the exact error (for example `GmailAPIError: Gmail OAuth token refresh rejected (HTTP 400): {"error": "invalid_grant", ...}`).

To switch back to Brevo, set `EMAIL_PROVIDER=brevo` (or clear it) and make sure `BREVO_API_KEY` is set.

## How to rotate secrets

- **Django SECRET_KEY**: generate new random key; update Render env var `DJANGO_SECRET_KEY` (or `SECRET_KEY`). Redeploy. Active sessions may be invalidated (signed cookies).
- **Database password**: rotate in Neon (or Postgres provider). Update `DATABASE_URL` in Render (password embedded). Redeploy and verify connectivity.
- **Brevo API key**: generate new key in Brevo; update `BREVO_API_KEY`. Test with `python manage.py send_test_email <recipient>`. Revoke old key.
- **Gmail API (if `EMAIL_PROVIDER=gmail_api`)**: to rotate the client secret, add a new secret on the Desktop OAuth client in Google Cloud and update `GMAIL_CLIENT_SECRET`. To rotate the refresh token, run `scripts/get_gmail_refresh_token.py` again and update `GMAIL_REFRESH_TOKEN`. Test with `send_test_email`. Then delete the old secret, or revoke the old grant at <https://myaccount.google.com/permissions>.
- **OCR.space API key**: rotate in OCR.space account; update `OCRSPACE_API_KEY`. Test OCR flow on a small document (with OCR_ENABLED true).
- **Twilio (if enabled)**: rotate Auth Token in Twilio Console; update `TWILIO_AUTH_TOKEN`. Also rotate Account SID only if required; update `TWILIO_ACCOUNT_SID`. Test WhatsApp send via `send_test_whatsapp`.
- **360dialog (if enabled)**: rotate the key in the 360dialog Hub; update `D360_API_KEY`. Rotate `D360_WEBHOOK_TOKEN` by setting a new value, then re-register the webhook with `python manage.py d360_set_webhook <new-url>`. Test an outbound send via `send_test_whatsapp`.

## Roll back a bad deploy

1. In Render, go to the service → Deploys → find last known-good commit → "Redeploy" that commit (or promote previous build).
2. If DB schema changed in bad deploy, restoring from a known-good backup may be required (see BACKUP_RESTORE). Only restore into empty DB or with care (migrations state).
3. Verify: `python manage.py check`, smoke test login/dashboard, key flows.

## Create the first superuser

- Locally: `python manage.py createsuperuser`.
- On Render: set `DJANGO_SUPERUSER_*` env vars and let `build.sh` run (createsuperuser --noinput; command ignores if user exists).

## Tests: how to run and duration

- All tests: `python manage.py test` (Django test runner). Suite includes unit/integration and CSS/backup tests added.
- Specific: `python manage.py test core.tests_backup`, `python manage.py test core.tests_ui_css`, `python manage.py test core.tests_global_search`, `python manage.py test core.tests_phase5`, `python manage.py test core.tests_email_whatsapp_fixes`, `python manage.py test core.tests_gmail_api`.
- Duration (verified in recent runs): full suite ~20s local (358 tests) including notifications/ocr/whatsapp tests with mocked network. Duration may vary by environment; mark as "verify" for Render exact timing.

## Common errors and causes

| Error | Cause / Fix |
|---|---|
| `ImproperlyConfigured: DJANGO_SECRET_KEY environment variable must be set in production.` | `SECRET_KEY`/`DJANGO_SECRET_KEY` missing when DEBUG False (RENDER present). Set secret in Render env. |
| CSRF failures (403 on POST) | Missing/incorrect `CSRF_TRUSTED_ORIGINS` or HTTPS behind proxy without proper headers. Ensure Render origin added (code auto-adds `RENDER_EXTERNAL_HOSTNAME`), and `SECURE_PROXY_SSL_HEADER` set when not DEBUG. |
| `'no such table'` after pulling new migrations locally | Run `python manage.py migrate`. If DB out of sync, consider recreating local DB or migrating. |
| File missing after redeploy (uploads) | Files uploaded to disk will be lost on ephemeral filesystem. This app uses `DatabaseFileStorage` (uploads stored in DB) so DB-backed uploads survive redeploys; ensure using DB storage paths (default for partner documents per code). |
| Brevo API rejected (401/403) | Invalid/rotated `BREVO_API_KEY`. Test with `send_test_email`. |
| Brevo rejected `400 sender not valid / not authorized` | `DEFAULT_FROM_EMAIL` (or a per-message From) is not a verified sender/domain in Brevo. Set `BREVO_SENDER_EMAIL` to a verified sender and redeploy. `send_test_email` prints the effective From. |
| Gmail `token refresh rejected (HTTP 400): invalid_grant` | The refresh token expired or was revoked. The most common cause is the OAuth consent screen still in **Testing** (tokens last 7 days). Publish the app (**In production**), run `scripts/get_gmail_refresh_token.py` again and update `GMAIL_REFRESH_TOKEN`. |
| Gmail `token refresh rejected (HTTP 401): invalid_client` | `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` are wrong, or the secret was deleted in Google Cloud. |
| Gmail API `HTTP 403` (`insufficient authentication scopes` / `Gmail API has not been used`) | The token was issued without the `gmail.send` scope, or the Gmail API is not enabled in the project. Enable it and/or generate a new token. |
| Gmail API `HTTP 429` / `Daily user sending limit exceeded` | Gmail sending limits (about 500 recipients/day for a free Gmail account). Lower `NOTIFY_EMAIL_DAILY_LIMIT` or move to Brevo/Resend. |
| `ImproperlyConfigured: Gmail API email is not configured; missing ...` | `EMAIL_PROVIDER=gmail_api` but one of the `GMAIL_*` variables is empty. |
| Notifications skipped `not configured` / `whatsapp notifications disabled` | WhatsApp needs `WHATSAPP_ENABLED=True` **and** configured provider credentials **and** per-partner opt-in. Run `python manage.py send_test_whatsapp +91...` to see the exact missing variable. |
| WhatsApp `number not in allowed list` for a valid number | Format difference in `WHATSAPP_ALLOWED_NUMBERS`. Entries are normalised now, but keep them E.164 (`+91...`) to be safe. |
| OCR.space errors / quota | `OCR_ENABLED` true but key missing/invalid, or `OCR_DAILY_LIMIT` reached, or file > `OCR_MAX_BYTES`. Check logs and limits. |
| OCR failed `Tesseract is not installed on this server` | `OCR_PROVIDER=tesseract` on the native Python deploy. Tesseract exists only in the Docker image; deploy with the `Dockerfile` (see `docs/ocr.md`) or set `OCR_PROVIDER=ocrspace`/`hybrid`. |
| OCR failed `tesseract timed out after 120s` | Slow free-tier CPU or a very large/multi-page file. Raise `OCR_TESSERACT_TIMEOUT` or lower `OCR_PDF_MAX_PAGES`, then **Retry OCR**. |
| WhatsApp sandbox restrictions | Twilio sandbox only accepts joined numbers/templates; 360dialog sandbox allows one fixed recipient, few messages and templates only for business-initiated sends. Channel disabled by default. |
| Inbound webhook 404 | `D360_WEBHOOK_TOKEN` unset or URL token does not match `D360_WEBHOOK_TOKEN`. Set the env var and re-register via `d360_set_webhook`. |
| Inbound webhook not matching a partner | Sender number not an approved partner's `whatsapp_number` (E.164), or the partner has not opted in. Check the `InboundWhatsAppMessage` row's `status`. |
| Webhook delivery slow after idle | Free Render instance sleeps; the first delivery after idle can be slow. Provider retries are safe (message ids are de-duplicated). |
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