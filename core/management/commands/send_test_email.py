from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Sends one test email through the configured email backend '
        '(the Brevo HTTPS API when BREVO_API_KEY is set). Prints the backend '
        'and resolved From address so a Brevo "sender not valid" error can be '
        'diagnosed quickly. Never prints the API key.'
    )

    def add_arguments(self, parser):
        parser.add_argument('recipient', help='Email address that should receive the test message.')

    def handle(self, *args, **options):
        recipient = (options['recipient'] or '').strip()
        if not recipient:
            raise CommandError('Recipient email address must not be empty.')
        if '@' not in recipient or ' ' in recipient:
            raise CommandError('Recipient email address is not valid: {!r}.'.format(recipient))

        sender = settings.DEFAULT_FROM_EMAIL
        # A verified Brevo sender, when configured, is what BrevoAPIEmailBackend
        # will actually use; show it so the operator knows what to verify.
        effective_sender = getattr(settings, 'BREVO_SENDER_EMAIL', '') or sender

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

        self.stdout.write('Backend: {}'.format(settings.EMAIL_BACKEND))
        self.stdout.write('From:    {}'.format(effective_sender))

        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            # Never prints the API key: exceptions from BrevoAPIEmailBackend
            # are logged with the key redacted.
            raise CommandError('Failed to send test email: {}'.format(exc))

        if sent:
            self.stdout.write(self.style.SUCCESS(
                'Success: sent {} message(s) to {}.'.format(sent, recipient)
            ))
        else:
            raise CommandError('No message was sent to {}.'.format(recipient))
