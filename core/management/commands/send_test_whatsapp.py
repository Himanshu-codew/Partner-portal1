from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.services.whatsapp import get_provider, redact
from core.utils import normalize_phone

DEFAULT_MESSAGE = (
    'Partner Portal test message. '
    'If you are reading this, outbound WhatsApp is working.'
)


class Command(BaseCommand):
    help = (
        'Sends one test WhatsApp message through the configured provider '
        '(the Twilio WhatsApp sandbox). Requires WHATSAPP_ENABLED and the '
        'Twilio settings; refuses numbers outside WHATSAPP_ALLOWED_NUMBERS.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'number', help='Destination in E.164 format, e.g. +919876543210.'
        )
        parser.add_argument(
            'message', nargs='?', default=DEFAULT_MESSAGE,
            help='Optional message text (defaults to a short test message).',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'WHATSAPP_ENABLED', False):
            raise CommandError(
                'WHATSAPP_ENABLED is off. Set WHATSAPP_ENABLED=True to send WhatsApp messages.'
            )

        provider = get_provider()
        if provider is None:
            raise CommandError(
                'Twilio is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN '
                'and TWILIO_WHATSAPP_FROM.'
            )

        try:
            number = normalize_phone(options['number'])
        except ValidationError as exc:
            raise CommandError('Invalid number: {}'.format('; '.join(exc.messages)))

        allowed = getattr(settings, 'WHATSAPP_ALLOWED_NUMBERS', None) or []
        if allowed and number not in allowed:
            raise CommandError(
                '{} is not in WHATSAPP_ALLOWED_NUMBERS; refusing to send.'.format(number)
            )

        result = provider.send_text(number, options['message'])
        if result.ok:
            self.stdout.write(self.style.SUCCESS(
                'Sent to {}: sid={} status={}'.format(number, result.message_id, result.status)
            ))
            return

        detail = 'twilio {}: {}'.format(result.error_code, result.error_message) \
            if result.error_code else result.error_message
        # redact() guarantees no token or SID leaves the process.
        raise CommandError('Failed to send to {}: {}'.format(number, redact(detail)))
