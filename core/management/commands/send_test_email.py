from django.core.management.base import BaseCommand, CommandError
from django.core.mail import EmailMessage


class Command(BaseCommand):
    help = (
        'Sends a test email to the given address through the configured '
        'email backend (the Brevo HTTPS API when BREVO_API_KEY is set).'
    )

    def add_arguments(self, parser):
        parser.add_argument('recipient', help='Email address that should receive the test message.')

    def handle(self, *args, **options):
        recipient = (options['recipient'] or '').strip()
        if not recipient:
            raise CommandError('Recipient email address must not be empty.')

        message = EmailMessage(
            subject='Partner Portal — test email',
            body=(
                'This is a test email from the Partner Portal.\n\n'
                'If you are reading it, outbound email is working and '
                'password reset messages can be delivered.\n'
            ),
            to=[recipient],
        )

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
