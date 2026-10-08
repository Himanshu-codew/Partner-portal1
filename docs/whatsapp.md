# WhatsApp notifications (Twilio sandbox)

Outbound WhatsApp messages are sent through the **Twilio WhatsApp sandbox**
using the Twilio Messages REST API over HTTPS. This phase is **outbound
only** — inbound webhooks are not implemented.

## How the sandbox works

- **Joining**: a recipient must first send `join <code>` (for example
  `join happy-blue-42`) to the sandbox number shown in the Twilio console.
  Only after that is the number allowed to exchange messages with the
  sandbox.
- **Session**: a sandbox session lasts **3 days**. After it expires the
  recipient must send `join <code>` again.
- **24-hour window**: free-form messages (like the ones this portal sends)
  only work within **24 hours of the recipient's last message to the
  sandbox**. Outside that window Twilio rejects the send with error
  `63016` — the notification is logged as `failed: twilio 63016: …` and
  the email channel is unaffected.
- **Trial limits**: a trial account has a limited number of free messages
  and can only deliver to numbers that have joined the sandbox. Set
  `WHATSAPP_ALLOWED_NUMBERS` to the few numbers you test with so the free
  quota is not burned by accident.

## Environment variables (Render)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `WHATSAPP_ENABLED` | yes (to send) | `False` | Master switch for the channel. |
| `WHATSAPP_PROVIDER` | no | `twilio` | Only `twilio` is implemented. |
| `TWILIO_ACCOUNT_SID` | yes | – | Twilio Account SID (starts with `AC`). |
| `TWILIO_AUTH_TOKEN` | yes | – | Twilio Auth Token — keep it secret. |
| `TWILIO_WHATSAPP_FROM` | yes | – | Sandbox sender, E.164 e.g. `+17372508034`. |
| `WHATSAPP_ALLOWED_NUMBERS` | recommended | – | Comma-separated E.164 allow-list. Empty = any number. |
| `NOTIFY_WHATSAPP_DAILY_LIMIT` | no | `50` | Max messages per day (`<= 0` = unlimited). |

If `WHATSAPP_ENABLED` is on but the Twilio settings are missing, the
channel logs `skipped: not configured` and nothing is ever sent.

## Sending a test message

```bash
python manage.py send_test_whatsapp +919876543210
python manage.py send_test_whatsapp +919876543210 "hello from the portal"
```

The command requires `WHATSAPP_ENABLED`, refuses numbers outside
`WHATSAPP_ALLOWED_NUMBERS`, and prints the Twilio message SID and status
(or the error). Secrets are never printed.

## What gets sent

One short plain text message per event (max 400 characters), rendered
from `templates/notifications/<event>.wa.txt`, for example:

```
Partner Portal: new reply on your ticket #12. Open: https://your-app.onrender.com/support/12/
```

Consent rules are strict: only approved partners who opted in
(`whatsapp_opt_in`), left `notify_whatsapp` on, and have a valid
`whatsapp_number` receive messages. Every attempt — sent, failed or
skipped — is recorded in `NotificationLog`, including the Twilio message
SID (`provider_message_id`) for sent messages.
