"""WhatsApp outbound providers (Phase 2B).

Sends plain text messages through the Twilio WhatsApp sandbox using
Twilio's REST API over HTTPS with the standard library only (``urllib``)
— the project must not gain new dependencies for this.

Design rules:
  * ``send_text()`` NEVER raises: every outcome (success, Twilio error,
    timeout, DNS failure, bad JSON…) comes back as a
    :class:`WhatsAppResult`.
  * The Auth Token and the Account SID are redacted from every string
    that can reach a log line or ``NotificationLog.error``.
  * Inbound webhooks are deliberately not implemented in this phase.
"""

import base64
import json
import logging
from dataclasses import dataclass

import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger('core.whatsapp')

# Twilio Messages REST resource (HTTPS, HTTP Basic auth).
API_BASE = 'https://api.twilio.com/2010-04-01'
TIMEOUT = 10  # seconds — a hung request must never stall a page render

# Shorten free-form error text before it is recorded anywhere.
ERROR_LIMIT = 160


@dataclass
class WhatsAppResult:
    """Outcome of one ``send_text()`` call. Never carries secrets."""

    ok: bool = False
    message_id: str = ''      # Twilio message SID, e.g. SMxxxx (sent only)
    status: str = ''          # Twilio status ('queued') or HTTP status
    error_code: str = ''      # Twilio error code, e.g. '63016'
    error_message: str = ''   # short, redacted human readable reason


def redact(text):
    """Strip Twilio (and email) credentials from a string."""
    text = str(text)
    for secret in (
        getattr(settings, 'TWILIO_AUTH_TOKEN', ''),
        getattr(settings, 'TWILIO_ACCOUNT_SID', ''),
        getattr(settings, 'BREVO_API_KEY', ''),
        getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
    ):
        if secret and secret in text:
            text = text.replace(secret, '[redacted]')
    return text


def _short(text, limit=ERROR_LIMIT):
    """Collapse whitespace and truncate so log fields stay small."""
    return ' '.join(redact(text).split())[:limit]


class WhatsAppProvider:
    """Interface for a WhatsApp delivery provider."""

    def send_text(self, to_e164, body):
        """Deliver one plain text message. Must never raise."""
        raise NotImplementedError


class TwilioWhatsAppProvider(WhatsAppProvider):
    """Twilio WhatsApp sandbox sender (outbound text only)."""

    def __init__(self, account_sid=None, auth_token=None, from_number=None):
        # None = "read from settings"; an explicit empty string means
        # "not configured" and must not fall back to settings.
        self.account_sid = (
            getattr(settings, 'TWILIO_ACCOUNT_SID', '') if account_sid is None else account_sid
        )
        self.auth_token = (
            getattr(settings, 'TWILIO_AUTH_TOKEN', '') if auth_token is None else auth_token
        )
        self.from_number = (
            getattr(settings, 'TWILIO_WHATSAPP_FROM', '') if from_number is None else from_number
        )

    @property
    def configured(self):
        return bool(self.account_sid and self.auth_token and self.from_number)

    def send_text(self, to_e164, body):
        to_e164 = (to_e164 or '').strip()
        if not to_e164:
            return WhatsAppResult(error_code='invalid', error_message='missing destination number')
        if not self.configured:
            return WhatsAppResult(error_code='not configured', error_message='missing Twilio settings')

        url = f'{API_BASE}/Accounts/{self.account_sid}/Messages.json'
        payload = urllib.parse.urlencode({
            'To': f'whatsapp:{to_e164}',
            'From': f'whatsapp:{self.from_number}',
            'Body': str(body or ''),
        }).encode('utf-8')
        credentials = base64.b64encode(
            f'{self.account_sid}:{self.auth_token}'.encode('utf-8')
        ).decode('ascii')

        request = urllib.request.Request(url, data=payload)
        request.add_header('Authorization', f'Basic {credentials}')
        request.add_header('Content-Type', 'application/x-www-form-urlencoded')

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode('utf-8', errors='replace')
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            return WhatsAppResult(
                ok=True,
                message_id=str(data.get('sid', '')),
                status=str(data.get('status', '')),
            )
        except urllib.error.HTTPError as exc:
            return self._from_http_error(exc)
        except urllib.error.URLError as exc:
            return WhatsAppResult(
                error_code='network',
                error_message=_short(getattr(exc, 'reason', exc)),
            )
        except (TimeoutError, OSError) as exc:
            return WhatsAppResult(error_code='network', error_message=_short(exc))
        except Exception as exc:  # noqa: BLE001 - send_text must never raise
            logger.error('twilio request failed: %s', _short(exc))
            return WhatsAppResult(error_code='error', error_message=_short(exc))

    @staticmethod
    def _from_http_error(exc):
        """Turn a Twilio 4xx/5xx JSON error body into a result."""
        raw = b''
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001 - body may already be consumed
            pass
        data = {}
        if raw:
            try:
                data = json.loads(raw.decode('utf-8', errors='replace'))
            except ValueError:
                data = {}
        code = str(data.get('code', '') or getattr(exc, 'code', '') or '')
        message = str(data.get('message', '') or getattr(exc, 'msg', '') or 'request rejected')
        return WhatsAppResult(
            ok=False,
            status=str(getattr(exc, 'code', '') or ''),
            error_code=code,
            error_message=_short(message),
        )


def get_provider():
    """Return the configured provider, or ``None`` when not set up.

    Never raises: an unknown provider name or missing credentials simply
    means "not configured", which the channel reports as a skip.
    """
    try:
        name = (getattr(settings, 'WHATSAPP_PROVIDER', 'twilio') or 'twilio').strip().lower()
        if name != 'twilio':
            return None
        provider = TwilioWhatsAppProvider()
        return provider if provider.configured else None
    except Exception:  # noqa: BLE001 - configuration must never crash delivery
        logger.exception('whatsapp provider lookup failed: %s', _short('provider error'))
        return None
