# WhatsApp (Phase 5 — outbound providers + inbound webhook)

The portal talks to WhatsApp through a small provider layer
(`core/services/whatsapp.py`). Two providers are supported:

| `WHATSAPP_PROVIDER` | Provider | Notes |
|---|---|---|
| `twilio` (default) | Twilio WhatsApp sandbox | Phase 2B behaviour, unchanged. |
| `360dialog` | 360dialog WhatsApp Business API | Phase 5; outbound text + inbound webhook. |

Outbound messages are one short plain text per event. Inbound messages
(360dialog only) are turned into ticket replies — see below.

## Outbound — Twilio sandbox

- Sandbox limits: a recipient must first text the sandbox; a session lasts
  a limited time and free-form sends outside the 24-hour customer service
  window are rejected with error `63016` (logged as `failed`, email is
  unaffected).
- Trial accounts can only deliver to numbers that have joined the sandbox.
  Set `WHATSAPP_ALLOWED_NUMBERS` so the free quota is not burned by accident.

## Outbound — 360dialog

- Sends a WhatsApp Cloud API text payload to
  `POST {D360_BASE_URL}/v1/messages` with the `D360-API-KEY` header (the
  destination is sent without a leading `+`).
- `D360_BASE_URL` defaults to the sandbox `https://waba-sandbox.360dialog.io`.
- Sandbox restrictions to be aware of: a single fixed recipient, a low
  message cap, and **predefined templates only** for business-initiated
  (non-reply) messages. Free-form replies within the 24-hour window are fine.
- The provider never raises: HTTP, DNS and timeout problems come back as a
  `failed` result and are logged with the credential redacted.

## Inbound webhook (360dialog)

Inbound messages create a ticket reply attributed to the matched partner.

- Endpoint: `POST /webhooks/whatsapp/<D360_WEBHOOK_TOKEN>/` (`csrf_exempt`).
  A wrong or missing token returns **404** and touches nothing. Valid
  requests always return **200** so the provider does not retry.
- Matching: the sender's `from` number is normalised to E.164 and matched
  against an **approved** partner's `whatsapp_number`.
- If the text matches `STOP` / `UNSUBSCRIBE` / `CANCEL`: notifications are
  turned off (`whatsapp_opt_in` and `notify_whatsapp`) and a one-time
  acknowledgement is sent. `START` re-enables `notify_whatsapp` **only** if
  the partner is still opted in.
- Otherwise, if the partner has opted in, the text is appended as a
  `TicketReply` (`source="whatsapp"`) on their most recently updated
  `OPEN` ticket. With no open ticket the message is ignored and a single
  "No open ticket found…" reply is sent (subject to the daily limit).
- Every received message id is stored in `InboundWhatsAppMessage`; a repeat
  of the same id is ignored (idempotent). Non-text messages and messages
  from unknown / unapproved / non-opted-in senders are recorded as
  `ignored`.
- Replies show in the ticket thread with a WhatsApp badge and appear in the
  staff notification feed like any partner reply.

### Registering the webhook

```bash
python manage.py d360_set_webhook https://your-app.onrender.com/webhooks/whatsapp/<D360_WEBHOOK_TOKEN>/
```

This POSTs `{"url": ...}` to `{D360_BASE_URL}/v1/configs/webhook`. The token
and API key are never printed. Note: the free Render instance sleeps, so the
first webhook delivery after idle can be slow.

## Environment variables (Render)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `WHATSAPP_ENABLED` | yes (to send) | `False` | Master switch for outbound sending. |
| `WHATSAPP_PROVIDER` | no | `twilio` | `twilio` or `360dialog`. |
| `TWILIO_ACCOUNT_SID` | for Twilio | – | Twilio Account SID (starts with `AC`). |
| `TWILIO_AUTH_TOKEN` | for Twilio | – | Twilio Auth Token — keep secret. |
| `TWILIO_WHATSAPP_FROM` | for Twilio | – | Sandbox sender, E.164 e.g. `+17372508034`. |
| `D360_API_KEY` | for 360dialog | – | Sent as the `D360-API-KEY` header — keep secret. |
| `D360_BASE_URL` | no | `https://waba-sandbox.360dialog.io` | API base URL. |
| `D360_WEBHOOK_TOKEN` | for inbound | – | Secret path segment of the webhook URL. |
| `WHATSAPP_ALLOWED_NUMBERS` | recommended | – | Comma-separated E.164 allow-list. Empty = any number. |
| `NOTIFY_WHATSAPP_DAILY_LIMIT` | no | `50` | Max messages per day (`<= 0` = unlimited). |

If `WHATSAPP_ENABLED` is on but the provider settings are missing, the
channel logs `skipped: not configured` and nothing is sent. Inbound replies
reuse the same guards (enabled, allow-list, daily limit).

## Sending a test message

```bash
python manage.py send_test_whatsapp +919876543210
python manage.py send_test_whatsapp +919876543210 "hello from the portal"
```

Works with either provider, requires `WHATSAPP_ENABLED`, refuses numbers
outside `WHATSAPP_ALLOWED_NUMBERS`, and prints the message id (or the
error). Secrets are never printed.

## Consent rules

Only approved partners who opted in (`whatsapp_opt_in`), left
`notify_whatsapp` on, and have a valid `whatsapp_number` receive messages.
Every outbound attempt — sent, failed or skipped — is recorded in
`NotificationLog`, including the provider message id for sent messages.
Inbound messages are recorded in `InboundWhatsAppMessage`.
