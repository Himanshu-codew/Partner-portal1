"""Regression tests for the email/WhatsApp notification fixes.

Covers:
* Brevo sender resolution (verified sender override + DEFAULT_FROM_EMAIL fallback)
* recipient email validation in EmailChannel
* normalised WHATSAPP_ALLOWED_NUMBERS matching
* provider-aware WhatsApp error prefix + provider config diagnostics
* send_test_email / send_test_whatsapp commands

Every HTTP call is mocked: these tests never touch the network.
"""

import io
import json
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core import email_backends
from core.services.notifications import EmailChannel, WhatsAppChannel, build_context
from core.services.whatsapp import (
    Dialog360WhatsAppProvider,
    get_provider,
    is_number_allowed,
    provider_config_problem,
)
from core.tests import BaseTestCase

MOCK_URL = 'core.services.whatsapp.urllib.request.urlopen'

TWILIO_ON = {
    'WHATSAPP_ENABLED': True,
    'WHATSAPP_PROVIDER': 'twilio',
    'TWILIO_ACCOUNT_SID': 'ACaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'TWILIO_AUTH_TOKEN': 'test_auth_token_1234567890',
    'TWILIO_WHATSAPP_FROM': '+17372508034',
    'WHATSAPP_ALLOWED_NUMBERS': [],
    'NOTIFY_WHATSAPP_DAILY_LIMIT': 50,
}


class FakeResponse:
    """Stand-in for the object urlopen() returns on success."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# =================================================================
# Brevo sender resolution
# =================================================================

class BrevoSenderResolutionTests(SimpleTestCase):

    def _message(self, from_email='Partner Portal <no-reply@example.com>'):
        return EmailMultiAlternatives(
            subject='subject',
            body='text',
            from_email=from_email,
            to=['recipient@example.com'],
        )

    def test_uses_message_from_email_by_default(self):
        payload = email_backends.BrevoAPIEmailBackend()._build_payload(self._message())
        self.assertEqual(
            payload['sender'], {'name': 'Partner Portal', 'email': 'no-reply@example.com'}
        )

    @override_settings(BREVO_SENDER_EMAIL='verified@portal.example', BREVO_SENDER_NAME='Portal Robots')
    def test_verified_sender_overrides_message_from(self):
        payload = email_backends.BrevoAPIEmailBackend()._build_payload(
            self._message('Personal Name <someone@gmail.com>')
        )
        self.assertEqual(
            payload['sender'], {'name': 'Portal Robots', 'email': 'verified@portal.example'}
        )

    @override_settings(
        BREVO_SENDER_EMAIL='verified@portal.example',
        DEFAULT_FROM_EMAIL='Partner Portal <no-reply@portal.example>',
    )
    def test_verified_sender_keeps_message_name_when_no_sender_name(self):
        payload = email_backends.BrevoAPIEmailBackend()._build_payload(
            self._message('Support Desk <support@gmail.com>')
        )
        self.assertEqual(
            payload['sender'], {'name': 'Support Desk', 'email': 'verified@portal.example'}
        )

    @override_settings(DEFAULT_FROM_EMAIL='Partner Portal <no-reply@portal.example>')
    def test_empty_from_falls_back_to_default_from_email(self):
        payload = email_backends.BrevoAPIEmailBackend()._build_payload(self._message(''))
        self.assertEqual(payload['sender']['email'], 'no-reply@portal.example')

    @override_settings(DEFAULT_FROM_EMAIL='Partner Portal <no-reply@portal.example>')
    def test_malformed_from_falls_back_to_default_from_email(self):
        payload = email_backends.BrevoAPIEmailBackend()._build_payload(self._message('not-an-email'))
        self.assertEqual(payload['sender']['email'], 'no-reply@portal.example')

    @override_settings(BREVO_API_KEY='brevo-test-key-not-real', BREVO_SENDER_EMAIL='verified@portal.example')
    def test_verified_sender_reaches_posted_payload(self):
        with mock.patch(
            'core.email_backends.urllib.request.urlopen',
            return_value=FakeResponse({'message': 'accepted'}),
        ) as urlopen:
            sent = email_backends.BrevoAPIEmailBackend().send_messages(
                [self._message('Personal <someone@gmail.com>')]
            )
        self.assertEqual(sent, 1)
        request = urlopen.call_args[0][0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['sender'], {'name': 'Personal', 'email': 'verified@portal.example'})


# =================================================================
# EmailChannel recipient validation
# =================================================================

class EmailChannelRecipientTests(BaseTestCase):

    def test_invalid_email_is_skipped(self):
        self.partner_user.email = 'not-an-email'
        self.partner_user.save(update_fields=['email'])
        result = EmailChannel().send(self.partner_user, 'subject', {'event': 'ticket_reply'})
        self.assertEqual((result.status, result.error), ('skipped', 'invalid email address'))
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_email_is_skipped(self):
        self.partner_user.email = ''
        self.partner_user.save(update_fields=['email'])
        result = EmailChannel().send(self.partner_user, 'subject', {'event': 'ticket_reply'})
        self.assertEqual((result.status, result.error), ('skipped', 'no email address'))


# =================================================================
# Allow-list normalisation
# =================================================================

class IsNumberAllowedTests(SimpleTestCase):

    def test_empty_list_allows_any_number(self):
        self.assertTrue(is_number_allowed('+919876543210', []))
        self.assertTrue(is_number_allowed('+919876543210', None))

    def test_matches_equivalent_representations(self):
        self.assertTrue(is_number_allowed('+919876543210', ['919876543210']))
        self.assertTrue(is_number_allowed('+919876543210', ['+919876543210']))
        self.assertTrue(is_number_allowed('+919876543210', ['+91 98765 43210']))

    def test_rejects_other_numbers(self):
        self.assertFalse(is_number_allowed('+919876543210', ['+911111111111']))


@override_settings(**TWILIO_ON)
class WhatsAppAllowListChannelTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.partner_profile.whatsapp_number = '+919876543210'
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.notify_whatsapp = True
        self.partner_profile.save()

    def _context(self):
        from support.models import Ticket
        ticket = Ticket.objects.create(
            partner=self.partner_profile, subject='s', description='d', status='OPEN',
        )
        return build_context('ticket_reply', 'subject', self.partner_user, {'ticket': ticket})

    @override_settings(WHATSAPP_ALLOWED_NUMBERS=['919876543210'])
    def test_unprefixed_allow_list_entry_still_matches(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'sid': 'SM1', 'status': 'queued'})) as urlopen:
            result = WhatsAppChannel().send(self.partner_user, 'subject', self._context())
        self.assertEqual(result.status, 'sent')
        urlopen.assert_called_once()

    @override_settings(WHATSAPP_ALLOWED_NUMBERS=['+911111111111'])
    def test_unlisted_number_is_skipped(self):
        with mock.patch(MOCK_URL) as urlopen:
            result = WhatsAppChannel().send(self.partner_user, 'subject', self._context())
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'number not in allowed list'))


# =================================================================
# Provider configuration diagnostics
# =================================================================

class ProviderConfigProblemTests(SimpleTestCase):

    @override_settings(WHATSAPP_ENABLED=False)
    def test_disabled_reports_enabled_flag(self):
        self.assertIn('WHATSAPP_ENABLED', provider_config_problem())

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER='twilio',
                       TWILIO_ACCOUNT_SID='', TWILIO_AUTH_TOKEN='', TWILIO_WHATSAPP_FROM='')
    def test_twilio_missing_settings_named(self):
        self.assertIn('TWILIO_ACCOUNT_SID', provider_config_problem())

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER='360dialog', D360_API_KEY='')
    def test_360dialog_missing_key_named(self):
        self.assertIn('D360_API_KEY', provider_config_problem())

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER='360dialog', D360_API_KEY='key')
    def test_360dialog_configured_is_ok(self):
        self.assertIsNone(provider_config_problem())

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER='bogus')
    def test_unknown_provider_named(self):
        self.assertIn('WHATSAPP_PROVIDER', provider_config_problem())

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_PROVIDER='360Dialog', D360_API_KEY='key')
    def test_provider_name_is_case_insensitive(self):
        self.assertIsInstance(get_provider(), Dialog360WhatsAppProvider)


# =================================================================
# Management commands
# =================================================================

class SendTestEmailCommandTests(BaseTestCase):

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_prints_backend_and_sender(self):
        out = io.StringIO()
        call_command('send_test_email', 'someone@example.com', stdout=out)
        text = out.getvalue()
        self.assertIn('locmem', text)
        self.assertIn('From:', text)

    def test_rejects_invalid_recipient(self):
        with self.assertRaises(CommandError):
            call_command('send_test_email', 'not-an-email')


@override_settings(**TWILIO_ON)
class SendTestWhatsappCommandTests(BaseTestCase):

    @override_settings(WHATSAPP_ALLOWED_NUMBERS=['919876543210'])
    def test_accepts_equivalent_allow_list_entry(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'sid': 'SM7', 'status': 'queued'})) as urlopen:
            out = io.StringIO()
            call_command('send_test_whatsapp', '+919876543210', 'hi', stdout=out)
        urlopen.assert_called_once()
        self.assertIn('twilio', out.getvalue())
        self.assertIn('SM7', out.getvalue())
