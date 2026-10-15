# Architecture

## Apps and responsibilities (verified)

- **accounts**: authentication flows (login/logout, password change/reset), user-facing account views. URLs included from root (`'', include('accounts.urls')`).
- **core**: shared infrastructure — middleware (`approval`, see below), services (notifications, OCR, email backend, WhatsApp providers), storage (`DatabaseFileStorage`), models (`StoredFile`, `NotificationLog`, `UserNotificationRead`), management commands (`purge_recycle_bin`, `send_test_email`, `send_test_whatsapp`, `d360_set_webhook`, `backup_data`), global search views (`search`, `search_suggest`), inbound WhatsApp webhook (`whatsapp_webhook`), recycle bin, notifications feed/mark-read, PWA endpoints (`manifest.webmanifest`, `service-worker.js`, `offline/`).
- **partners**: partner profiles and KYC documents (`PartnerProfile`, `PartnerDocument`), partner list/update, KYC review, upload/download via DB storage. Soft-deleted models in partners include PartnerProfile and PartnerDocument.
- **leads**: leads CRUD/status, partner-scoped access.
- **orders**: orders linked to leads/partners, order status, commissions.
- **support**: tickets and ticket replies (thread), staff/partner visibility.
- **portal_content**: announcements and documents (`Announcement`, `Document`) with visibility (`visible_to` M2M in places), file size display, login-protected downloads via core/partners flows.

## Main models and relations (high-level, verified)

- `User` (auth) 1:1 with `PartnerProfile` (partners.models). PartnerProfile has `is_approved`, contact prefs, soft-delete.
- `PartnerDocument` (partners): belongs to `PartnerProfile`, stores `file` path/name via DB storage, `ocr_text`, `extracted_*`, `ocr_status`, `review_status`, `uploaded_at`; soft-deleted.
- `Lead` (leads), `Order` (orders) linked to partner/profile context; `Order` links to `Lead`.
- `Ticket` and `TicketReply` (support): partner-scoped tickets, threaded replies (`TicketReply.source` is `portal` or `whatsapp`).
- `InboundWhatsAppMessage` (support): one row per inbound 360dialog message (`wa_message_id` unique, `from_number`, `body`, optional `matched_ticket`, `status`), used for de-duplication and auditing.
- `Announcement`, `Document` (portal_content): visibility to partners via M2M where applicable; active flags.
- `StoredFile` (core): DB-backed binary storage (name, content, content_type, size).
- `NotificationLog` (core): per-channel delivery attempt (event, channel, status, error redacted, provider_message_id).
- `UserNotificationRead` (core): last read timestamp per user.

SoftDeleteModel base provides `deleted_at`, `deleted_by`, `deleted_reason`, managers `objects`/`deleted_objects`, `soft_delete()`, `hard_delete()` (see `core/models.py` context in codebase).

## Request flow and approval middleware (verified)

Approval middleware: `core.middleware.ApprovalMiddleware`.
- Exempt prefixes: `/static/`, `/media/`, `/manifest.webmanifest`, `/service-worker.js`, `/offline/`, password reset paths (`/password_reset/`, `/reset/`), `logout`, `profile`, `profile_edit`, `password_change`, `approval_pending` (by view name logic).
- For authenticated users with a partner profile that is **not approved**: redirect to `approval_pending` (302). For AJAX (`x-requested-with: XMLHttpRequest`) to `/notifications/` endpoints, middleware returns 403 (per code). `/search/` is **not** exempt — unapproved partners are blocked by middleware (redirects to approval pending) in addition to view-level checks; this is the intended behaviour (verified in tests).
- Approved partners visiting `approval_pending` are redirected to `dashboard`.
- Non-partner staff/superusers are not blocked by partner-approval rule.
- Login required paths are enforced by views using `@login_required(login_url='/login/')`.

URLs order: core PWA/search/recycle/notifications first, then app includes, then accounts root include (so root routes like dashboard/login handled by accounts/core as configured).

## Notification service (verified)

`core.services.notifications.notify()` (design rules in code):
- Never raises; delivery problems logged; every attempt recorded in `NotificationLog`.
- Runs inside `transaction.on_commit` (no delivery if transaction rolls back).
- Deduplication window `DEDUPE_TTL=60s` for identical event context per user/channel.
- Daily caps: `NOTIFY_EMAIL_DAILY_LIMIT` (default 200), `NOTIFY_WHATSAPP_DAILY_LIMIT` (default 50) with `QUOTA_TTL=24h`. Channel failures do not take other channels down.
- Events: `ticket_reply`, `lead_status_changed`, `order_status_changed`, `commission_paid`, `partner_approval_changed`, `announcement_published`, `kyc_reviewed`.
- Email via Django email backend; Brevo HTTPS backend used when `BREVO_API_KEY` set. WhatsApp via a provider in `core.services.whatsapp` (`twilio` or `360dialog`, selected by `WHATSAPP_PROVIDER`).
- Inbound WhatsApp (360dialog): `POST /webhooks/whatsapp/<token>/` (`core.views.whatsapp_webhook`, `csrf_exempt`) verifies the token with `hmac.compare_digest` (404 on mismatch), ignores status-only payloads, and turns text messages into `TicketReply(source='whatsapp')` on the partner's open ticket. It also handles STOP/START opt-out/in. `send_whatsapp_reply` in the notifications service sends the short system replies under the same limits.
- Errors redacted (secrets stripped) before logging/storage.

## OCR pipeline (verified)

`core.services.ocr`:
- Provider interface returns `OCRResult` (never raises). API key only in request header; stripped from logs/errors.
- Post-commit processing: `process_document(document_id)` starts a daemon thread after upload transaction commits (no worker process on Render free tier). Thread closes DB connections when done.
- Gated by `OCR_ENABLED` (default False). Provider `ocrspace` (default), `tesseract` (local engine, Docker deploy only) or `hybrid` (Tesseract, OCR.space fallback); local runs are serialised by a lock and do not count toward the daily limit. Daily limit `OCR_DAILY_LIMIT` (100), max bytes `OCR_MAX_BYTES` (1MB default). Status flow tracked on `PartnerDocument.ocr_status`/timestamps.
- Privacy: Aadhaar numbers masked out of `ocr_text` before storing (comment in model); OCR output are suggestions only (never auto-written back).
- Errors short and redacted.

## File storage (verified)

`DatabaseFileStorage` (`core.storage`): stores bytes in `core.StoredFile` (name, content binary, content_type, size). `_save` reads all bytes (handles chunks), stores row by name. `_open` returns `ContentFile`. `url()` is not used to expose public URLs in normal flows; downloads go through login-required views. This keeps uploads intact across redeploys (ephemeral disk on Render free).

## PWA behaviour (verified from code/views/settings context)

- Endpoints: `/manifest.webmanifest`, `/service-worker.js`, `/offline/` (public, routed via `core.urls`).
- Service worker: generated by `service_worker` view; contains a CACHE_NAME and a list of URLs to precache (including static assets referenced). In `DEBUG=True`, the view disables/avoids aggressive caching in the served SW (code sets `debug` flag in SW context) — see `core/views.py` service_worker implementation and `docs/pwa.md`. Precaching is limited to what the view includes.
- Manifest: `web_manifest` view returns JSON with app name/icons/start URL.
- Offline: `/offline/` view serves offline page.
- Installability: UI includes Install app button (topbar) wired via PWA install prompt handling in templates.
- Notes: service worker caching strategy is controlled by the view-generated SW; in development (DEBUG) caching is intentionally disabled to avoid stale assets. Manifest/icons paths must exist under static or be served.

## Caching / middleware notes (relevant)

- No global CACHES configured → locmem by default. Search suggest uses `cache.get/set` with fixed window.
- Approval middleware blocks unapproved partners (non-AJAX) including `/search/` (not exempt). AJAX notifications special-cased.
- Manifest strictness adjusted in tests; see settings for `STATICFILES_MANIFEST_STRICT` behavior in test contexts.
