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

from core.utils import normalize_phone

logger = logging.getLogger('core.whatsapp')

# Twilio Messages REST resource (HTTPS, HTTP Basic auth).
API_BASE = 'https://api.twilio.com/2010-04-01'

# 360dialog WhatsApp Business API (sandbox by default; override with D360_BASE_URL).
D360_DEFAULT_BASE_URL = 'https://waba-sandbox.360dialog.io'
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
    """Strip WhatsApp (and email) credentials from a string."""
    text = str(text)
    for secret in (
        getattr(settings, 'TWILIO_AUTH_TOKEN', ''),
        getattr(settings, 'TWILIO_ACCOUNT_SID', ''),
        getattr(settings, 'D360_API_KEY', ''),
        getattr(settings, 'D360_WEBHOOK_TOKEN', ''),
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

    name = 'twilio'

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


class Dialog360WhatsAppProvider(WhatsAppProvider):
    """360dialog (WhatsApp Business API) sender — outbound text only.

    Uses the 360dialog sandbox endpoint by default
    (``https://waba-sandbox.360dialog.io``) with the ``D360-API-KEY`` header
    and the WhatsApp Cloud API message payload. Standard library only.
    """

    name = '360dialog'

    def __init__(self, api_key=None, base_url=None):
        # None = "read from settings"; an explicit empty string means
        # "not configured" and must not fall back to settings.
        self.api_key = (
            getattr(settings, 'D360_API_KEY', '') if api_key is None else api_key
        )
        self.base_url = (
            getattr(settings, 'D360_BASE_URL', D360_DEFAULT_BASE_URL)
            if base_url is None else base_url
        ).rstrip('/')

    @property
    def configured(self):
        return bool(self.api_key and self.base_url)

    def send_text(self, to_e164, body):
        to_e164 = (to_e164 or '').strip()
        if not to_e164:
            return WhatsAppResult(error_code='invalid', error_message='missing destination number')
        if not self.configured:
            return WhatsAppResult(error_code='not configured', error_message='missing 360dialog settings')

        # Cloud API expects the number as digits only (no leading '+').
        to_digits = to_e164[1:] if to_e164.startswith('+') else to_e164
        url = f'{self.base_url}/v1/messages'
        payload = json.dumps({
            'messaging_product': 'whatsapp',
            'to': to_digits,
            'type': 'text',
            'text': {'body': str(body or '')},
        }).encode('utf-8')

        request = urllib.request.Request(url, data=payload)
        request.add_header('D360-API-KEY', self.api_key)
        request.add_header('Content-Type', 'application/json')

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode('utf-8', errors='replace')
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            messages = data.get('messages') or []
            message_id = ''
            if messages and isinstance(messages[0], dict):
                message_id = str(messages[0].get('id', ''))
            return WhatsAppResult(ok=True, message_id=message_id, status='sent')
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
            logger.error('360dialog request failed: %s', _short(exc))
            return WhatsAppResult(error_code='error', error_message=_short(exc))

    @staticmethod
    def _from_http_error(exc):
        """Turn a 360dialog 4xx/5xx JSON error body into a result."""
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
        # 360dialog errors look like {"error": {"message": "...", "code": ...}}
        error = data.get('error') if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = str(error.get('code', '') or error.get('type', ''))
            message = str(error.get('message', '') or 'request rejected')
        elif isinstance(error, str):
            code = ''
            message = error
        else:
            code = str(getattr(exc, 'code', '') or '')
            message = str(data.get('message', '') if isinstance(data, dict) else '') or 'request rejected'
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
        if name == '360dialog':
            provider = Dialog360WhatsAppProvider()
            return provider if provider.configured else None
        if name != 'twilio':
            return None
        provider = TwilioWhatsAppProvider()
        return provider if provider.configured else None
    except Exception:  # noqa: BLE001 - configuration must never crash delivery
        logger.exception('whatsapp provider lookup failed: %s', _short('provider error'))
        return None


# Required settings per provider, used for clear "what is missing" messages.
PROVIDER_REQUIRED_SETTINGS = {
    'twilio': ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM'),
    '360dialog': ('D360_API_KEY',),
}


def provider_config_problem():
    """Return a short human reason why WhatsApp cannot send, or ``None``.

    Used by the management commands to explain a Render log entry such as
    ``skipped: not configured`` without leaking any secret value.
    """
    if not getattr(settings, 'WHATSAPP_ENABLED', False):
        return 'WHATSAPP_ENABLED is not set to True'
    name = (getattr(settings, 'WHATSAPP_PROVIDER', 'twilio') or 'twilio').strip().lower()
    if name not in PROVIDER_REQUIRED_SETTINGS:
        return (
            "WHATSAPP_PROVIDER must be 'twilio' or '360dialog' "
            f"(got {name!r})"
        )
    missing = [
        var for var in PROVIDER_REQUIRED_SETTINGS[name]
        if not str(getattr(settings, var, '') or '').strip()
    ]
    if missing:
        return 'missing required setting(s): ' + ', '.join(missing)
    return None


def is_number_allowed(number, allowed=None):
    """Whether ``number`` is permitted by the ``WHATSAPP_ALLOWED_NUMBERS`` list.

    An empty/``None`` list means "any number". Both the target and every list
    entry are normalised to E.164 first, so a value written as ``919876543210``
    still matches ``+919876543210`` — otherwise a valid recipient would be
    silently skipped as "number not in allowed list".
    """
    if allowed is None:
        allowed = getattr(settings, 'WHATSAPP_ALLOWED_NUMBERS', None) or []
    if not allowed:
        return True

    try:
        target = normalize_phone(number)
    except Exception:  # noqa: BLE001 - fall back to a literal comparison
        target = str(number or '').strip()

    for entry in allowed:
        candidate = str(entry or '').strip()
        if candidate == target:
            return True
        try:
            if normalize_phone(candidate) == target:
                return True
        except Exception:  # noqa: BLE001 - a bad list entry must not break others
            continue
    return False
