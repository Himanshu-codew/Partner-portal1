# Changelog

All notable changes to this project are recorded here based on git history.

## 0. Security hardening (baseline) — verify
- Hardened for security and production readiness on Render (settings baseline). **verify**: exact scope.

## 1. Storage and password reset — verify
- Database-backed file storage and password reset flows added/adjusted. **verify**: details from commits.

## 2. Ticket replies and notifications (Phase 2A/2B)
- Ticket reply threads, in-app notifications feed, notification service (email + WhatsApp channels with dedupe/quota/NotificationLog), email backend integration (Brevo), management commands for test sends. See git: Phase 2B related commits (`3bc4580`).

## 3. OCR for KYC and invoice documents (Phase 3)
- OCR pipeline (OCR.space), daemon post-commit processing, privacy-aware masking, status tracking, daily limits/size caps. Commit `8a4f7ed phase3: OCR for KYC and invoice documents`.

## 4. PWA and mobile usability (Phase 4A)
- PWA endpoints (manifest, service worker, offline), install button, mobile polish. Commit `aeaa7d2 phase4a: PWA and mobile usability`.

## 4B. UI consistency and global search (Phase 4B)
- Ticket list status control fix (single status control), global search (`/search/`, `/search/suggest/`), top-bar form with type-ahead, grouped results. Commits `9cf6ef1 phase4b: single status control on ticket list`, `abd0963 phase4b: global search`.

## Fix: select arrow overlapping text
- Shared CSS fix for `.form-select` (padding-right, truncation, dark-mode arrow). Commit `c1fdce7 fix: select arrow overlapping text`. Added `core.tests_ui_css.py`.

## Handoff documentation and backup command
- Added `README.md`, `.env.example`, `docs/RUNBOOK.md`, `docs/ARCHITECTURE.md`, `docs/BACKUP_RESTORE.md`, `docs/CLIENT_HANDOFF.md`, `CHANGELOG.md`. Commit `0eabc3d docs: handoff documentation and backup command`.
- Added `core/management/commands/backup_data.py`, tests `core.tests_backup.py`.
- Updated `.gitignore` to exclude `backups/` and backup JSON patterns.
- Verified via `python manage.py check` and tests.

## Fix: backup_data without server-side cursors
- `backup_data` now disables/restores server-side cursors on the `default` connection (Neon/pgbouncer safe), removes partial files on failure, and never prints the DB URL. Added `DB_DISABLE_SERVER_SIDE_CURSORS` setting. Commit `c6a0d15 fix: backup_data without server-side cursors`.

## 5. 360dialog WhatsApp provider and inbound webhook (Phase 5)
- New `Dialog360WhatsAppProvider` (Cloud API text send via `D360-API-KEY`), selected by `WHATSAPP_PROVIDER=360dialog`; Twilio still supported.
- Inbound webhook `POST /webhooks/whatsapp/<D360_WEBHOOK_TOKEN>/`: token-guarded, turns WhatsApp texts into `TicketReply(source='whatsapp')` on the partner's open ticket, handles STOP/START opt-out/in, de-duplicates via new `InboundWhatsAppMessage` model (migration `support/0006_inboundwhatsappmessage`).
- New `send_whatsapp_reply` helper and `d360_set_webhook` command; tests in `core.tests_phase5`. Docs updated (`docs/whatsapp.md`, `RUNBOOK`, `ARCHITECTURE`, `.env.example`).
