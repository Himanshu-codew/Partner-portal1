"""Register the inbound webhook URL with the 360dialog provider.

Usage:
    python manage.py d360_set_webhook https://<host>/webhooks/whatsapp/<D360_WEBHOOK_TOKEN>/

The token is part of the URL and is read from the environment — this command
never prints or logs it. Only the (redacted) provider error is shown on failure.
"""

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.whatsapp import D360_DEFAULT_BASE_URL, redact

TIMEOUT = 10


class Command(BaseCommand):
    help = (
        'Registers the inbound WhatsApp webhook URL with 360dialog by POSTing '
        '<D360_BASE_URL>/v1/configs/webhook with body {"url": <https_url>}. '
        'Requires D360_API_KEY. Never prints the API key or webhook token.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'url',
            help=(
                'Public HTTPS webhook URL in the form '
                'https://<host>/webhooks/whatsapp/<D360_WEBHOOK_TOKEN>/'
            ),
        )

    def handle(self, *args, **options):
        url = (options['url'] or '').strip()
        if not url:
            raise CommandError('A webhook URL is required.')
        if not url.lower().startswith('https://'):
            raise CommandError('The webhook URL must be an HTTPS URL.')

        api_key = getattr(settings, 'D360_API_KEY', '') or ''
        if not api_key:
            raise CommandError('D360_API_KEY is not configured; set it before registering.')
        base_url = (getattr(settings, 'D360_BASE_URL', D360_DEFAULT_BASE_URL) or D360_DEFAULT_BASE_URL).rstrip('/')

        endpoint = f'{base_url}/v1/configs/webhook'
        payload = json.dumps({'url': url}).encode('utf-8')
        request = urllib.request.Request(endpoint, data=payload)
        request.add_header('D360-API-KEY', api_key)
        request.add_header('Content-Type', 'application/json')

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                status = getattr(response, 'status', None) or response.getcode()
                response.read()
            self.stdout.write(self.style.SUCCESS(
                f'Webhook registered (HTTP {status}) at {endpoint}.'
            ))
        except urllib.error.HTTPError as exc:
            detail = self._read_error(exc)
            raise CommandError(
                f'360dialog rejected the webhook (HTTP {getattr(exc, "code", "?")}): {redact(detail)}'
            )
        except urllib.error.URLError as exc:
            raise CommandError(f'Could not reach 360dialog: {redact(getattr(exc, "reason", exc))}')
        except Exception as exc:  # noqa: BLE001 - report, never leak a key
            raise CommandError(f'Webhook registration failed: {redact(exc)}')

    @staticmethod
    def _read_error(exc):
        raw = b''
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001
            pass
        if not raw:
            return getattr(exc, 'msg', '') or 'request rejected'
        text = raw.decode('utf-8', errors='replace')
        try:
            data = json.loads(text)
        except ValueError:
            return text
        error = data.get('error') if isinstance(data, dict) else None
        if isinstance(error, dict):
            return str(error.get('message', '') or error.get('type', '') or 'request rejected')
        if isinstance(error, str):
            return error
        if isinstance(data, dict) and data.get('message'):
            return str(data['message'])
        return text
