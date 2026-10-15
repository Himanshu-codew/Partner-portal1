"""Email backends for the Partner Portal.

Render's free tier blocks outbound SMTP, so production mail is sent over HTTPS
instead of through a mail server: either Brevo's API
(https://developers.brevo.com/reference/sendtransacemail, BrevoAPIEmailBackend)
or the Gmail API (GmailAPIEmailBackend, selected with EMAIL_PROVIDER=gmail_api).

The API key comes from settings (BREVO_API_KEY, read from the environment).
It is never logged and is redacted from anything raised or recorded here.

The From address is resolved so Brevo never sees an unverified sender:
BREVO_SENDER_EMAIL (when set) always wins, otherwise the message From is used
and finally DEFAULT_FROM_EMAIL is used as a fallback.
"""

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from email.utils import parseaddr

import requests
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


def _valid_email(value):
    """Cheap sanity check: Brevo rejects anything that is not an address."""
    text = str(value or '').strip()
    if not text or ' ' in text or '@' not in text:
        return False
    local, _, domain = text.partition('@')
    return bool(local) and '.' in domain and not text.startswith('@')


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Sends django.core.mail messages through the Brevo HTTPS API."""

    def _sender(self, message):
        """Resolve the From address, preferring the verified Brevo sender.

        Order of precedence:
          1. ``BREVO_SENDER_EMAIL`` (a confirmed Brevo sender) — always wins, so
             transactional mail is never rejected for an unverified From.
          2. the message's own ``from_email`` (Django defaults this to
             ``DEFAULT_FROM_EMAIL``), when it looks like a real address.
          3. ``DEFAULT_FROM_EMAIL``.
        """
        name, email = parseaddr(message.from_email or '')
        if not _valid_email(email):
            name, email = parseaddr(getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '')

        forced_email = getattr(settings, 'BREVO_SENDER_EMAIL', '') or ''
        if _valid_email(forced_email):
            forced_name = getattr(settings, 'BREVO_SENDER_NAME', '') or ''
            email = forced_email
            name = forced_name or name or 'Partner Portal'

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


# ---------------------------------------------------------------------------
# Gmail API backend
# ---------------------------------------------------------------------------
#
# Sends through the Gmail REST API over HTTPS with an OAuth refresh token, so
# mail keeps flowing on Render (where SMTP is blocked) without Brevo. Only the
# ``requests`` library is used. Gmail always sends from the account that
# authorised the refresh token (GMAIL_SENDER).
#
# Credentials come from settings: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and
# GMAIL_REFRESH_TOKEN. None of them, nor the short-lived access token, is ever
# logged or included in a raised error.

GMAIL_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GMAIL_SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
GMAIL_TOKEN_EXPIRY_MARGIN = 60  # refresh this many seconds before expiry

# Process-wide access token cache: {'token', 'expires_at', 'client_id'}.
_gmail_token_cache = {}
_gmail_token_lock = threading.Lock()


def _reset_gmail_token_cache():
    """Forget the cached access token (used by tests)."""
    with _gmail_token_lock:
        _gmail_token_cache.clear()


class GmailAPIError(Exception):
    """A Gmail API or OAuth token request failed. The message holds no secrets."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _redact_gmail(text, extra=()):
    """Remove OAuth secrets and tokens from text before it is logged or raised."""
    text = str(text)
    secrets = [
        getattr(settings, 'GMAIL_CLIENT_SECRET', '') or '',
        getattr(settings, 'GMAIL_REFRESH_TOKEN', '') or '',
        _gmail_token_cache.get('token') or '',
        *extra,
    ]
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[redacted]')
    return text


def _response_excerpt(response, extra=()):
    """A short, redacted excerpt of an HTTP response body."""
    try:
        body = response.text or ''
    except Exception:
        body = ''
    return _redact_gmail(body, extra)[:300]


class GmailAPIEmailBackend(BaseEmailBackend):
    """Sends django.core.mail messages through the Gmail API (HTTPS)."""

    def _credentials(self):
        values = {
            name: (getattr(settings, name, '') or '').strip()
            for name in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN')
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ImproperlyConfigured(
                'Gmail API email is not configured; missing {}.'.format(', '.join(missing))
            )
        return values['GMAIL_CLIENT_ID'], values['GMAIL_CLIENT_SECRET'], values['GMAIL_REFRESH_TOKEN']

    def _access_token(self, force_refresh=False):
        """Return a cached access token, refreshing it ~60s before it expires."""
        client_id, client_secret, refresh_token = self._credentials()
        with _gmail_token_lock:
            cache = _gmail_token_cache
            if (
                not force_refresh
                and cache.get('token')
                and cache.get('client_id') == client_id
                and cache.get('expires_at', 0) - GMAIL_TOKEN_EXPIRY_MARGIN > time.time()
            ):
                return cache['token']

            try:
                response = requests.post(
                    GMAIL_TOKEN_URL,
                    data={
                        'grant_type': 'refresh_token',
                        'client_id': client_id,
                        'client_secret': client_secret,
                        'refresh_token': refresh_token,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as exc:
                detail = _redact_gmail(exc)[:300]
                logger.error('Gmail OAuth token request failed: %s', detail)
                raise GmailAPIError('Gmail OAuth token request failed: {}'.format(detail)) from None

            if response.status_code != 200:
                excerpt = _response_excerpt(response)
                logger.error(
                    'Gmail OAuth token refresh rejected (HTTP %s): %s',
                    response.status_code, excerpt,
                )
                raise GmailAPIError(
                    'Gmail OAuth token refresh rejected (HTTP {}): {}'.format(
                        response.status_code, excerpt),
                    status_code=response.status_code,
                )

            try:
                data = response.json()
                token = data['access_token']
                expires_in = int(data.get('expires_in', 3600))
            except (ValueError, KeyError, TypeError):
                logger.error('Gmail OAuth token response did not contain an access token.')
                raise GmailAPIError('Gmail OAuth token response did not contain an access token.') from None

            cache.clear()
            cache.update({
                'token': token,
                'expires_at': time.time() + expires_in,
                'client_id': client_id,
            })
            return token

    def _raw_message(self, message):
        """Build the MIME message and return it base64url encoded."""
        mime = message.message()
        if message.bcc:
            # Django keeps Bcc out of the headers; Gmail reads it from the raw
            # message to deliver the blind copies and strips it before sending.
            mime['Bcc'] = ', '.join(str(address) for address in message.bcc)
        return base64.urlsafe_b64encode(mime.as_bytes()).decode('ascii')

    def _post_message(self, raw, token):
        return requests.post(
            GMAIL_SEND_URL,
            json={'raw': raw},
            headers={'Authorization': 'Bearer {}'.format(token)},
            timeout=REQUEST_TIMEOUT,
        )

    def _send(self, message):
        raw = self._raw_message(message)
        token = self._access_token()
        try:
            response = self._post_message(raw, token)
            if response.status_code == 401:
                # The cached token was revoked or expired early: refresh once.
                token = self._access_token(force_refresh=True)
                response = self._post_message(raw, token)
        except requests.RequestException as exc:
            detail = _redact_gmail(exc, extra=(token,))[:300]
            logger.error('Gmail API request failed: %s', detail)
            raise GmailAPIError('Gmail API request failed: {}'.format(detail)) from None

        if not 200 <= response.status_code < 300:
            excerpt = _response_excerpt(response, extra=(token,))
            logger.error(
                'Gmail API rejected the message (HTTP %s): %s',
                response.status_code, excerpt,
            )
            raise GmailAPIError(
                'Gmail API rejected the message (HTTP {}): {}'.format(
                    response.status_code, excerpt),
                status_code=response.status_code,
            )
        logger.info('Gmail API accepted the message (HTTP %s)', response.status_code)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                self._send(message)
            except Exception:
                # The failure is already logged (without secrets or tokens).
                if self.fail_silently:
                    continue
                raise
            sent += 1
        return sent
