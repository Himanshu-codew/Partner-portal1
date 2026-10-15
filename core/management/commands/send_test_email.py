from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Sends one test email through the active email backend (Brevo HTTPS '
        'API, Gmail API, SMTP or console, see EMAIL_PROVIDER). Prints the '
        'backend and resolved From address, then success or the exact error. '
        'Never prints API keys, OAuth secrets or tokens.'
    )

    def add_arguments(self, parser):
        parser.add_argument('recipient', help='Email address that should receive the test message.')

    def handle(self, *args, **options):
        recipient = (options['recipient'] or '').strip()
        if not recipient:
            raise CommandError('Recipient email address must not be empty.')
        if '@' not in recipient or ' ' in recipient:
            raise CommandError('Recipient email address is not valid: {!r}.'.format(recipient))

        backend = settings.EMAIL_BACKEND
        sender = settings.DEFAULT_FROM_EMAIL
        effective_sender = sender
        if backend.endswith('BrevoAPIEmailBackend'):
            # A verified Brevo sender, when configured, is what BrevoAPIEmailBackend
            # will actually use; show it so the operator knows what to verify.
            effective_sender = getattr(settings, 'BREVO_SENDER_EMAIL', '') or sender
        elif backend.endswith('GmailAPIEmailBackend'):
            # Gmail always sends from the account that authorised the token.
            effective_sender = getattr(settings, 'GMAIL_SENDER', '') or sender

        message = EmailMessage(
            subject='Partner Portal - test email',
            body=(
                'This is a test email from the Partner Portal.\n\n'
                'If you are reading it, outbound email is working and '
                'password reset messages can be delivered.\n'
            ),
            from_email=sender,
            to=[recipient],
        )

        self.stdout.write('Backend: {}'.format(backend))
        self.stdout.write('From:    {}'.format(effective_sender))

        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            # Backend errors are already redacted: no API keys, secrets or tokens.
            raise CommandError('Failed to send test email: {}: {}'.format(type(exc).__name__, exc))

        if sent:
            self.stdout.write(self.style.SUCCESS(
                'Success: sent {} message(s) to {}.'.format(sent, recipient)
            ))
        else:
            raise CommandError('No message was sent to {}.'.format(recipient))
