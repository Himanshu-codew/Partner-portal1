# Client Handoff

This is a plain-language checklist of decisions/inputs the client must provide. Items marked "verify" indicate exact values/policies not determinable from the checked source.

## Hosting

- [ ] **Hosting provider/plan:** Render free web service sleeps after inactivity; free Render Postgres may expire. For real use, recommend an always-on paid plan (Render paid web service) and a paid/larger database (Neon paid or Render managed Postgres). **verify**: target plan/cost.
- [ ] **Postgres:** Project uses Neon Postgres in production via `DATABASE_URL` (per README). If moving, update `DATABASE_URL`. **verify**: which Neon branch/region.
- [ ] **Custom domain:** If using custom domain, configure DNS (CNAME/ALIAS) and add to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. Render HTTPS handled if configured. **verify**: domain name.

## Email (Brevo) and deliverability

- [ ] **Brevo account/domain auth:** Using Brevo API (`BREVO_API_KEY`). Set up Brevo domain authentication (SPF/DKIM/DMARC) for the sender domain so emails don't land in spam. **verify**: sender domain, Brevo sender identity.
- [ ] **From address:** Set `DEFAULT_FROM_EMAIL` to an address on the authenticated domain. **verify**: chosen address.
- [ ] **Rate limits:** Default `NOTIFY_EMAIL_DAILY_LIMIT=200`. Adjust if expected volume differs. **verify**: expected email volume.

## WhatsApp (if enabling)

- [ ] **Decision:** WhatsApp channel exists but is **disabled by default** (`WHATSAPP_ENABLED=False`). Client must decide to enable only after meeting requirements. **verify**: enable/keep disabled.
- [ ] **Meta Business Portfolio + WhatsApp number:** Need a dedicated WhatsApp Business number and approved message templates. Free Twilio sandbox only accepts pre-made templates and sandbox numbers. **verify**: number, templates, WABA setup.
- [ ] **Twilio credentials:** If enabling, provide `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`. Restrict `WHATSAPP_ALLOWED_NUMBERS`. **verify**: allowed recipients.
- [ ] **Consent:** Ensure opt-in/opt-out handled (PartnerProfile has `whatsapp_opt_in` fields) and comply with WhatsApp policies. **verify**: consent policy.

## OCR and KYC privacy

- [ ] **OCR provider decision:** Currently configured for OCR.space (`OCR_PROVIDER=ocrspace`). Client must confirm provider and terms. **verify**: provider choice.
- [ ] **API key/limits:** If enabling (`OCR_ENABLED=True`), set `OCRSPACE_API_KEY`, review `OCR_DAILY_LIMIT` (100) and `OCR_MAX_BYTES` (1MB). **verify**: limits.
- [ ] **Privacy/consent:** Documents sent to third-party OCR service. Code masks Aadhaar numbers in `ocr_text` before storing; OCR output are suggestions only. Client must ensure consent to send KYC docs to third party and meet data protection requirements (never store full Aadhaar numbers). **verify**: consent text/process.
- [ ] **Data minimization/retention:** Decide retention period for uploaded KYC docs and OCR text. **verify**: retention policy.

## Data retention, backups, responsibility

- [ ] **Backup responsibility:** Assign an owner for backups (who runs/takes care of them). Backups contain personal data and password hashes.
- [ ] **Backup cadence/retention:** Decide how often to back up (daily recommended minimum if changing often) and how many generations to keep, where to store (outside repo, encrypted/private). **verify**: cadence/retention/location.
- [ ] **Restore testing:** Schedule restore test at least quarterly. **verify**: schedule/owner.
- [ ] **Purge policy:** Recycle bin purge runs via `purge_recycle_bin` (default 30 days). Decide if/when to schedule as cron job. **verify**: purge policy/schedule.
- [ ] **GDPR/PII handling:** Clarify data subject requests (access/delete) process given soft-delete + hard-delete. **verify**: process/owner.

## Security & ops

- [ ] **Secrets owner:** Single owner responsible for rotating secrets (SECRET_KEY, DB password, Brevo key, OCR key, Twilio if enabled). **verify**: owner name/contact.
- [ ] **Superuser access:** Create initial superuser (via build.sh or locally) and restrict admin access. **verify**: who has admin access.
- [ ] **Monitoring/logging:** Decide log retention and alerting for errors (notifications/OCR). **verify**: monitoring tool/retention.
- [ ] **PWA:** Manifest/icons present; service worker disabled in DEBUG. Client may want custom app name/icons. **verify**: branding/icons.
- [ ] **File storage note:** Uploads use DB storage (survive redeploys). No external S3 configured by default; if large files expected, consider external storage — current approach stores bytes in DB (`StoredFile`). **verify**: expected file sizes/volume.

## Acceptance

- [ ] **Smoke test:** Login, leads/orders/tickets, announcements, KYC upload+review flow (with OCR toggled appropriately), notifications, global search, recycle bin, PWA install.
- [ ] **Email test:** `send_test_email` to authenticated domain recipient.
- [ ] **Backup test:** Take a test backup and restore into empty test DB, verify counts.
- [ ] **Handoff docs reviewed:** README, RUNBOOK, ARCHITECTURE, BACKUP_RESTORE, this document all read/accepted.
