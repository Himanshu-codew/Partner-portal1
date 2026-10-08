"""Phase 2B — WhatsApp outgoing via the Twilio sandbox.

Every HTTP call is mocked: these tests must never touch the network.
"""

import base64
import io
import json
import urllib.parse
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from urllib.error import HTTPError, URLError

from core.models import NotificationLog
from core.services import notify
from core.services.notifications import (
    EVENTS,
    WhatsAppChannel,
    build_context,
)
from core.services.whatsapp import (
    TwilioWhatsAppProvider,
    WhatsAppProvider,
    WhatsAppResult,
    get_provider,
)
from core.tests import BaseTestCase
from portal_content.models import Announcement
from support.models import TicketReply

SID = 'ACaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
TOKEN = 'test_auth_token_1234567890'
FROM = '+17372508034'
PARTNER_NUMBER = '+919876543210'

# Explicit settings so the tests behave the same even if the developer's
# environment has real Twilio credentials set.
TWILIO_OFF = {
    'WHATSAPP_ENABLED': False,
    'TWILIO_ACCOUNT_SID': '',
    'TWILIO_AUTH_TOKEN': '',
    'TWILIO_WHATSAPP_FROM': '',
}
TWILIO_ON = {
    'WHATSAPP_ENABLED': True,
    'WHATSAPP_PROVIDER': 'twilio',
    'TWILIO_ACCOUNT_SID': SID,
    'TWILIO_AUTH_TOKEN': TOKEN,
    'TWILIO_WHATSAPP_FROM': FROM,
    'WHATSAPP_ALLOWED_NUMBERS': [],
    'NOTIFY_WHATSAPP_DAILY_LIMIT': 50,
}

MOCK_URL = 'core.services.whatsapp.urllib.request.urlopen'


class FakeResponse:
    """Stand-in for the object urlopen() returns on success."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def twilio_error(code, message, http_status=400):
    """A Twilio error body as urllib raises it for 4xx/5xx responses."""
    body = json.dumps({'status': http_status, 'code': code, 'message': message}).encode('utf-8')
    return HTTPError(
        'https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json'.format(SID),
        http_status, 'Bad Request', {}, io.BytesIO(body),
    )


# =================================================================
# Provider layer (pure HTTP behaviour, no database)
# =================================================================

@override_settings(**TWILIO_ON)
class TwilioProviderTests(SimpleTestCase):

    def make_provider(self):
        return TwilioWhatsAppProvider(
            account_sid=SID, auth_token=TOKEN, from_number=FROM,
        )

    def test_request_url_method_auth_and_prefixes(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['request'] = request
            captured['timeout'] = timeout
            return FakeResponse({'sid': 'SM1234', 'status': 'queued'})

        with mock.patch(MOCK_URL, side_effect=fake_urlopen):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hello there')

        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, 'SM1234')
        self.assertEqual(result.status, 'queued')
        self.assertEqual(result.error_code, '')
        self.assertEqual(result.error_message, '')

        request = captured['request']
        self.assertEqual(
            request.full_url,
            'https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json'.format(SID),
        )
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(captured['timeout'], 10)

        expected_auth = 'Basic ' + base64.b64encode(
            '{}:{}'.format(SID, TOKEN).encode('utf-8')
        ).decode('ascii')
        self.assertEqual(request.get_header('Authorization'), expected_auth)

        fields = urllib.parse.parse_qs(request.data.decode('utf-8'))
        self.assertEqual(fields['To'], ['whatsapp:{}'.format(PARTNER_NUMBER)])
        self.assertEqual(fields['From'], ['whatsapp:{}'.format(FROM)])
        self.assertEqual(fields['Body'], ['Hello there'])

    def test_http_400_twilio_error_is_returned_not_raised(self):
        with mock.patch(MOCK_URL, side_effect=twilio_error(
            63016, 'The message cannot be sent outside the 24 hour window.'
        )):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')

        self.assertIsInstance(result, WhatsAppResult)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, '63016')
        self.assertEqual(result.status, '400')
        self.assertIn('24 hour window', result.error_message)
        self.assertEqual(result.message_id, '')

    def test_timeout_is_returned_not_raised(self):
        with mock.patch(MOCK_URL, side_effect=URLError('connection timed out')):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 'network')
        self.assertIn('timed out', result.error_message)

        with mock.patch(MOCK_URL, side_effect=TimeoutError('timed out')):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 'network')

    def test_token_and_sid_are_redacted_from_errors(self):
        with mock.patch(MOCK_URL, side_effect=twilio_error(
            20003, 'Authenticate failed for {} using {}'.format(SID, TOKEN)
        )):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')

        self.assertFalse(result.ok)
        self.assertNotIn(TOKEN, result.error_message)
        self.assertNotIn(SID, result.error_message)
        self.assertIn('[redacted]', result.error_message)

    def test_unexpected_error_is_returned_not_raised(self):
        with mock.patch(MOCK_URL, side_effect=ValueError('garbage response')):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertFalse(result.ok)
        self.assertIn('garbage response', result.error_message)

    def test_unconfigured_provider_refuses_without_http(self):
        provider = TwilioWhatsAppProvider(account_sid='', auth_token='', from_number='')
        with mock.patch(MOCK_URL) as urlopen:
            result = provider.send_text(PARTNER_NUMBER, 'Hi')
        urlopen.assert_not_called()
        self.assertFalse(result.ok)

    def test_get_provider_requires_full_configuration(self):
        with override_settings(TWILIO_AUTH_TOKEN=''):
            self.assertIsNone(get_provider())
        with override_settings(WHATSAPP_PROVIDER='other'):
            self.assertIsNone(get_provider())
        self.assertIsInstance(get_provider(), TwilioWhatsAppProvider)


# =================================================================
# WhatsAppChannel skip rules
# =================================================================

@override_settings(**TWILIO_OFF)
class WhatsAppChannelSkipTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.ticket = self.make_ticket()
        self.channel = WhatsAppChannel()

    def consent_whatsapp(self, profile=None, number=PARTNER_NUMBER):
        profile = profile or self.partner_profile
        profile.whatsapp_number = number
        profile.whatsapp_opt_in = True
        profile.whatsapp_opt_in_at = timezone.now()
        profile.notify_whatsapp = True
        profile.save()
        return profile

    def context_for(self, user=None):
        user = user or self.partner_user
        return build_context(
            'ticket_reply', EVENTS['ticket_reply'], user,
            {'ticket': self.ticket},
        )

    def test_skipped_when_whatsapp_disabled(self):
        self.consent_whatsapp()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'not configured'))

    @override_settings(WHATSAPP_ENABLED=True, TWILIO_ACCOUNT_SID='',
                       TWILIO_AUTH_TOKEN='', TWILIO_WHATSAPP_FROM='')
    def test_skipped_when_twilio_settings_missing(self):
        self.consent_whatsapp()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'not configured'))

    @override_settings(**TWILIO_ON)
    def test_skipped_without_whatsapp_profile(self):
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.staff, 'subject', self.context_for(self.staff))
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'no whatsapp profile'))

    @override_settings(**TWILIO_ON)
    def test_skipped_for_unapproved_partner(self):
        self.consent_whatsapp(self.unapproved_profile)
        context = build_context(
            'partner_approval_changed', EVENTS['partner_approval_changed'],
            self.unapproved_user, {'profile': self.unapproved_profile},
        )
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.unapproved_user, 'subject', context)
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'partner not approved'))

    @override_settings(**TWILIO_ON)
    def test_skipped_without_opt_in(self):
        self.consent_whatsapp()
        self.partner_profile.whatsapp_opt_in = False
        self.partner_profile.save()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual(
            (result.status, result.error),
            ('skipped', 'whatsapp notifications disabled'),
        )

    @override_settings(**TWILIO_ON)
    def test_skipped_without_notify_whatsapp(self):
        self.consent_whatsapp()
        self.partner_profile.notify_whatsapp = False
        self.partner_profile.save()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual(
            (result.status, result.error),
            ('skipped', 'whatsapp notifications disabled'),
        )

    @override_settings(**TWILIO_ON)
    def test_skipped_without_number(self):
        self.consent_whatsapp()
        self.partner_profile.whatsapp_number = ''
        self.partner_profile.save()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual((result.status, result.error), ('skipped', 'missing whatsapp number'))

    @override_settings(**{**TWILIO_ON, 'WHATSAPP_ALLOWED_NUMBERS': ['+911111111111']})
    def test_skipped_when_number_not_in_allowed_list(self):
        self.consent_whatsapp()
        with mock.patch(MOCK_URL) as urlopen:
            result = self.channel.send(self.partner_user, 'subject', self.context_for())
        urlopen.assert_not_called()
        self.assertEqual(
            (result.status, result.error),
            ('skipped', 'number not in allowed list'),
        )

    @override_settings(**{**TWILIO_ON, 'NOTIFY_WHATSAPP_DAILY_LIMIT': 1})
    def test_daily_whatsapp_limit_respected(self):
        self.consent_whatsapp()
        with mock.patch(MOCK_URL, return_value=FakeResponse({'sid': 'SM1', 'status': 'queued'})) as urlopen:
            first = self.channel.send(self.partner_user, 'subject', self.context_for())
            second = self.channel.send(self.partner_user, 'subject', self.context_for())
        self.assertEqual(first.status, 'sent')
        self.assertEqual(
            (second.status, second.error),
            ('skipped', 'daily whatsapp limit reached'),
        )
        self.assertEqual(urlopen.call_count, 1)


# =================================================================
# Full notify() pipeline with a mocked provider
# =================================================================

@override_settings(**TWILIO_ON)
class WhatsAppNotifyTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.ticket = self.make_ticket()
        self.reply = TicketReply.objects.create(
            ticket=self.ticket, author=self.staff, message='We are on it.'
        )
        self.partner_profile.whatsapp_number = PARTNER_NUMBER
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.whatsapp_opt_in_at = timezone.now()
        self.partner_profile.notify_whatsapp = True
        self.partner_profile.save()

    def test_success_sends_both_channels_and_stores_sid(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['request'] = request
            return FakeResponse({'sid': 'SM999', 'status': 'queued'})

        with mock.patch(MOCK_URL, side_effect=fake_urlopen):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    self.partner_user, 'ticket_reply',
                    {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
                )

        self.assertEqual(result.status, 'queued')
        self.assertEqual(len(mail.outbox), 1)

        email_log = NotificationLog.objects.get(channel='email')
        self.assertEqual(email_log.status, 'sent')
        self.assertEqual(email_log.provider_message_id, '')

        wa_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(wa_log.status, 'sent')
        self.assertEqual(wa_log.error, '')
        self.assertEqual(wa_log.provider_message_id, 'SM999')

        fields = urllib.parse.parse_qs(captured['request'].data.decode('utf-8'))
        self.assertEqual(fields['To'], ['whatsapp:{}'.format(PARTNER_NUMBER)])
        body = fields['Body'][0]
        self.assertTrue(body.startswith('Partner Portal:'))
        self.assertIn('/support/{}/'.format(self.ticket.pk), body)

    def test_failure_does_not_stop_email_and_stores_no_secret(self):
        error = twilio_error(
            63016,
            'outside the 24 hour window (token {} sid {})'.format(TOKEN, SID),
        )
        with mock.patch(MOCK_URL, side_effect=error):
            with self.assertLogs('core.notifications', level='INFO') as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    result = notify(
                        self.partner_user, 'ticket_reply',
                        {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
                    )

        # notify() itself never fails, and the email still goes out.
        self.assertEqual(result.status, 'queued')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationLog.objects.get(channel='email').status, 'sent')

        wa_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(wa_log.status, 'failed')
        self.assertIn('twilio 63016', wa_log.error)
        self.assertNotIn(TOKEN, wa_log.error)
        self.assertNotIn(SID, wa_log.error)

        log_output = '\n'.join(logs.output)
        self.assertNotIn(TOKEN, log_output)
        self.assertNotIn(SID, log_output)

    def test_failure_result_never_raises(self):
        with mock.patch(MOCK_URL, side_effect=URLError('network unreachable')):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    self.partner_user, 'ticket_reply',
                    {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
                )
        self.assertEqual(result.status, 'queued')
        wa_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(wa_log.status, 'failed')
        self.assertEqual(NotificationLog.objects.get(channel='email').status, 'sent')

    @override_settings(**TWILIO_OFF)
    def test_disabled_channel_still_logs_and_sends_email(self):
        with mock.patch(MOCK_URL) as urlopen:
            with self.captureOnCommitCallbacks(execute=True):
                notify(
                    self.partner_user, 'ticket_reply',
                    {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
                )
        urlopen.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)
        wa_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual((wa_log.status, wa_log.error), ('skipped', 'not configured'))

    @override_settings(WHATSAPP_ALLOWED_NUMBERS=['+911111111111'])
    def test_disallowed_number_never_reaches_the_provider(self):
        with mock.patch(MOCK_URL) as urlopen:
            with self.captureOnCommitCallbacks(execute=True):
                notify(
                    self.partner_user, 'ticket_reply',
                    {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
                )
        urlopen.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)
        wa_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(
            (wa_log.status, wa_log.error),
            ('skipped', 'number not in allowed list'),
        )


# =================================================================
# .wa.txt templates: one per event, short, plain text, with a link
# =================================================================

class WhatsAppTemplateTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.ticket = self.make_ticket()
        self.reply = TicketReply.objects.create(
            ticket=self.ticket, author=self.staff, message='We are on it.'
        )

    def render_wa(self, event, context):
        full = build_context(event, EVENTS[event], self.partner_user, context)
        return render_to_string('notifications/{}.wa.txt'.format(event), full).strip()

    def test_every_event_has_a_short_plain_text_template(self):
        announcement = Announcement.objects.create(title='Big news', content='Details here.')
        contexts = {
            'ticket_reply': {'ticket': self.ticket, 'reply': self.reply},
            'lead_status_changed': {'lead': self.make_lead()},
            'order_status_changed': {'order': self.make_order()},
            'commission_paid': {'order': self.make_order()},
            'partner_approval_changed': {'profile': self.partner_profile},
            'announcement_published': {'announcement': announcement},
        }
        self.assertEqual(set(contexts), set(EVENTS))

        for event, context in contexts.items():
            with self.subTest(event=event):
                body = self.render_wa(event, context)
                self.assertTrue(body.startswith('Partner Portal:'))
                self.assertLess(len(body), 400)
                self.assertIn('http', body)          # a portal link is present
                self.assertNotIn('<', body)          # plain text, never HTML

    def test_long_content_stays_under_the_limit(self):
        self.ticket.subject = 'x' * 400
        self.ticket.save()
        self.partner_profile.company_name = 'y' * 400
        self.partner_profile.save()
        announcement = Announcement.objects.create(title='z' * 400, content='c' * 2000)
        lead = self.make_lead()
        lead.customer_name = 'n' * 400
        lead.save()

        bodies = {
            'ticket_reply': self.render_wa(
                'ticket_reply', {'ticket': self.ticket, 'reply': self.reply}),
            'partner_approval_changed': self.render_wa(
                'partner_approval_changed', {'profile': self.partner_profile}),
            'announcement_published': self.render_wa(
                'announcement_published', {'announcement': announcement}),
            'lead_status_changed': self.render_wa(
                'lead_status_changed', {'lead': lead}),
        }
        for event, body in bodies.items():
            with self.subTest(event=event):
                self.assertLess(len(body), 400)


# =================================================================
# send_test_whatsapp management command
# =================================================================

@override_settings(**TWILIO_ON)
class SendTestWhatsappCommandTests(BaseTestCase):

    def test_refuses_when_disabled(self):
        with override_settings(**TWILIO_OFF):
            with self.assertRaisesRegex(CommandError, 'WHATSAPP_ENABLED'):
                call_command('send_test_whatsapp', PARTNER_NUMBER)

    def test_refuses_when_twilio_not_configured(self):
        with override_settings(WHATSAPP_ENABLED=True, TWILIO_ACCOUNT_SID='',
                               TWILIO_AUTH_TOKEN='', TWILIO_WHATSAPP_FROM=''):
            with self.assertRaisesRegex(CommandError, 'not configured'):
                call_command('send_test_whatsapp', PARTNER_NUMBER)

    @override_settings(WHATSAPP_ALLOWED_NUMBERS=['+911111111111'])
    def test_refuses_number_outside_allowed_list(self):
        with mock.patch(MOCK_URL) as urlopen:
            with self.assertRaisesRegex(CommandError, 'WHATSAPP_ALLOWED_NUMBERS'):
                call_command('send_test_whatsapp', PARTNER_NUMBER)
        urlopen.assert_not_called()

    def test_rejects_invalid_number(self):
        with mock.patch(MOCK_URL) as urlopen:
            with self.assertRaisesRegex(CommandError, 'Invalid number'):
                call_command('send_test_whatsapp', 'not-a-number')
        urlopen.assert_not_called()

    def test_sends_and_prints_sid_and_status(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'sid': 'SM42', 'status': 'queued'})):
            out = io.StringIO()
            call_command('send_test_whatsapp', PARTNER_NUMBER, 'hi there', stdout=out)
        output = out.getvalue()
        self.assertIn('SM42', output)
        self.assertIn('queued', output)
        self.assertIn(PARTNER_NUMBER, output)
        self.assertNotIn(TOKEN, output)

    def test_prints_error_on_failure(self):
        with mock.patch(MOCK_URL, side_effect=twilio_error(63016, 'outside the 24 hour window')):
            with self.assertRaisesRegex(CommandError, '63016'):
                call_command('send_test_whatsapp', PARTNER_NUMBER)


# =================================================================
# Interface sanity
# =================================================================

class ProviderInterfaceTests(SimpleTestCase):

    def test_base_provider_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            WhatsAppProvider().send_text('+919876543210', 'hi')

    def test_result_defaults(self):
        result = WhatsAppResult()
        self.assertFalse(result.ok)
        self.assertEqual(result.message_id, '')
        self.assertEqual(result.status, '')
        self.assertEqual(result.error_code, '')
        self.assertEqual(result.error_message, '')
