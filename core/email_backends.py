"""Email backends for the Partner Portal.

Render's free tier blocks outbound SMTP, so production mail is sent through
Brevo's HTTPS API (https://developers.brevo.com/reference/sendtransacemail)
instead of a mail server.

The API key comes from settings (BREVO_API_KEY, read from the environment).
It is never logged and is redacted from anything raised or recorded here.
"""

import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger('core.email_backends')

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'
REQUEST_TIMEOUT = 10  # seconds


def _redact(text):
    """Remove the API key from a string before it is logged or raised."""
    api_key = getattr(settings, 'BREVO_API_KEY', '') or ''
    if api_key and api_key in text:
        return text.replace(api_key, '[redacted]')
    return text


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Sends django.core.mail messages through the Brevo HTTPS API."""

    def _sender(self, message):
        name, email = parseaddr(message.from_email or '')
        if not email:
            name, email = parseaddr(settings.DEFAULT_FROM_EMAIL)
        return {'name': name or 'Partner Portal', 'email': email}

    def _html_content(self, message):
        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                return content
        return None

    def _build_payload(self, message):
        payload = {
            'sender': self._sender(message),
            'to': [{'email': address} for address in message.to],
            'subject': message.subject or '',
            'textContent': message.body or '',
        }
        html_content = self._html_content(message)
        if html_content is not None:
            payload['htmlContent'] = html_content
        return payload

    def _error_detail(self, exc):
        """Return the API error body with the key redacted."""
        try:
            detail = exc.read().decode('utf-8', errors='replace')
        except Exception:
            detail = str(exc.reason)
        return _redact(detail)[:500]

    def _post(self, payload):
        api_key = getattr(settings, 'BREVO_API_KEY', '')
        if not api_key:
            raise ImproperlyConfigured(
                'BREVO_API_KEY is not configured; cannot send email through the Brevo API.'
            )

        request = urllib.request.Request(
            BREVO_API_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'api-key': api_key,
                'accept': 'application/json',
                'content-type': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                status = response.getcode()
                response.read()
        except OSError as exc:
            # HTTPError and URLError both subclass OSError.
            if isinstance(exc, urllib.error.HTTPError):
                logger.error(
                    'Brevo API rejected the message (HTTP %s): %s',
                    exc.code,
                    self._error_detail(exc),
                )
            else:
                logger.error('Brevo API request failed: %s', _redact(str(exc)))
            raise

        logger.info('Brevo API accepted the message (HTTP %s)', status)
        return status

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent = 0
        for message in email_messages:
            if not message.to:
                continue
            try:
                self._post(self._build_payload(message))
            except Exception:
                # The failure is already logged (without the API key).
                if self.fail_silently:
                    continue
                raise
            sent += 1
        return sent
