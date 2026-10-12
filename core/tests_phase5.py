"""Phase 5 — 360dialog WhatsApp provider and inbound webhook.

All HTTP is mocked; no test ever touches the network.
"""

import io
import json
import urllib.error
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from core.services.whatsapp import (
    Dialog360WhatsAppProvider,
    get_provider,
)
from core.tests import BaseTestCase
from support.models import InboundWhatsAppMessage, Ticket, TicketReply

PARTNER_NUMBER = '+919876543210'
OTHER_NUMBER = '+910000000000'
API_KEY = 'd360_secret_key_ABC123'
BASE_URL = 'https://waba-sandbox.360dialog.io'
WEBHOOK_TOKEN = 'test-webhook-token-xyz'

MOCK_URL = 'core.services.whatsapp.urllib.request.urlopen'

D360_SETTINGS = {
    'WHATSAPP_ENABLED': True,
    'WHATSAPP_PROVIDER': '360dialog',
    'D360_API_KEY': API_KEY,
    'D360_BASE_URL': BASE_URL,
    'D360_WEBHOOK_TOKEN': WEBHOOK_TOKEN,
    'TWILIO_ACCOUNT_SID': '',
    'TWILIO_AUTH_TOKEN': '',
    'TWILIO_WHATSAPP_FROM': '',
    'WHATSAPP_ALLOWED_NUMBERS': [],
    'NOTIFY_WHATSAPP_DAILY_LIMIT': 50,
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._body = json.dumps(payload or {}).encode('utf-8')
        self.status = status

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def http_error(body, status=400, url=BASE_URL + '/v1/messages'):
    return urllib.error.HTTPError(url, status, 'Bad Request', {}, io.BytesIO(body.encode('utf-8')))


def wa_payload(msg_id, from_number, text=None, msg_type='text'):
    message = {'id': msg_id, 'from': from_number, 'type': msg_type}
    if msg_type == 'text':
        message['text'] = {'body': text}
    return {'entry': [{'changes': [{'value': {'messages': [message]}}]}]}


# =================================================================
# Provider layer
# =================================================================

@override_settings(**D360_SETTINGS)
class Dialog360ProviderTests(SimpleTestCase):

    def make_provider(self):
        return Dialog360WhatsAppProvider(api_key=API_KEY, base_url=BASE_URL)

    def test_payload_url_and_headers(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['request'] = request
            captured['timeout'] = timeout
            return FakeResponse({'messages': [{'id': 'wamid.OUT1'}]})

        with mock.patch(MOCK_URL, side_effect=fake_urlopen):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hello there')

        request = captured['request']
        self.assertEqual(request.full_url, BASE_URL + '/v1/messages')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('D360-api-key'), API_KEY)
        self.assertEqual(captured['timeout'], 10)

        body = json.loads(request.data.decode('utf-8'))
        self.assertEqual(body['messaging_product'], 'whatsapp')
        self.assertEqual(body['to'], '919876543210')  # leading '+' stripped
        self.assertEqual(body['type'], 'text')
        self.assertEqual(body['text']['body'], 'Hello there')

        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, 'wamid.OUT1')

    def test_http_error_json_body_is_returned_not_raised(self):
        err = http_error(json.dumps({'error': {'message': 'Bad number', 'code': 100}}))
        with mock.patch(MOCK_URL, side_effect=err):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_message, 'Bad number')

    def test_network_error_is_returned_not_raised(self):
        with mock.patch(MOCK_URL, side_effect=urllib.error.URLError('down')):
            result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 'network')

    def test_api_key_never_in_errors_or_logs(self):
        with mock.patch(MOCK_URL, side_effect=ValueError(f'boom {API_KEY}')):
            with self.assertLogs('core.whatsapp', level='ERROR') as logs:
                result = self.make_provider().send_text(PARTNER_NUMBER, 'Hi')
        self.assertNotIn(API_KEY, result.error_message)
        self.assertNotIn(API_KEY, '\n'.join(logs.output))

    def test_unconfigured_refuses_without_http(self):
        provider = Dialog360WhatsAppProvider(api_key='', base_url=BASE_URL)
        with mock.patch(MOCK_URL) as urlopen:
            result = provider.send_text(PARTNER_NUMBER, 'Hi')
        urlopen.assert_not_called()
        self.assertFalse(result.ok)

    def test_get_provider_selects_360dialog(self):
        self.assertIsInstance(get_provider(), Dialog360WhatsAppProvider)

    @override_settings(WHATSAPP_PROVIDER='something-else')
    def test_get_provider_unknown_returns_none(self):
        self.assertIsNone(get_provider())


# =================================================================
# Inbound webhook
# =================================================================

@override_settings(**D360_SETTINGS)
class WhatsAppWebhookTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.partner_profile.whatsapp_number = PARTNER_NUMBER
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.notify_whatsapp = True
        self.partner_profile.save()

    def _post(self, payload, token=WEBHOOK_TOKEN):
        return self.client.post(
            reverse('whatsapp_webhook', args=[token]),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def _open_ticket(self, partner=None):
        return Ticket.objects.create(
            partner=partner or self.partner_profile, subject='Help needed',
            description='please help', status='OPEN',
        )

    # ── token guarding ─────────────────────────────────────────

    def test_wrong_token_returns_404_and_touches_nothing(self):
        resp = self._post(wa_payload('w1', PARTNER_NUMBER, 'hello'), token='wrong')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(InboundWhatsAppMessage.objects.count(), 0)
        self.assertEqual(TicketReply.objects.count(), 0)

    @override_settings(D360_WEBHOOK_TOKEN='')
    def test_missing_token_configuration_returns_404(self):
        resp = self._post(wa_payload('w1', PARTNER_NUMBER, 'hello'))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(InboundWhatsAppMessage.objects.count(), 0)

    # ── happy path + idempotency ───────────────────────────────

    def test_text_message_creates_reply_on_open_ticket(self):
        ticket = self._open_ticket()
        with mock.patch(MOCK_URL) as urlopen:
            resp = self._post(wa_payload('w1', PARTNER_NUMBER, 'I need help'))
        self.assertEqual(resp.status_code, 200)
        urlopen.assert_not_called()  # no reply needed when matched

        reply = TicketReply.objects.get()
        self.assertEqual(reply.ticket_id, ticket.pk)
        self.assertEqual(reply.author_id, self.partner_user.pk)
        self.assertEqual(reply.source, 'whatsapp')
        self.assertEqual(reply.message, 'I need help')

        record = InboundWhatsAppMessage.objects.get()
        self.assertEqual(record.status, InboundWhatsAppMessage.STATUS_PROCESSED)
        self.assertEqual(record.matched_ticket_id, ticket.pk)

    def test_duplicate_message_id_is_ignored(self):
        self._open_ticket()
        payload = wa_payload('w-dup', PARTNER_NUMBER, 'one')
        self._post(payload)
        self._post(payload)
        self.assertEqual(TicketReply.objects.count(), 1)
        self.assertEqual(InboundWhatsAppMessage.objects.count(), 1)

    def test_status_only_payload_returns_200_and_changes_nothing(self):
        payload = {'entry': [{'changes': [{'value': {'statuses': [{'id': 'x', 'status': 'delivered'}]}}]}]}
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InboundWhatsAppMessage.objects.count(), 0)
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_non_text_message_is_ignored(self):
        with mock.patch(MOCK_URL) as urlopen:
            resp = self._post(wa_payload('w-img', PARTNER_NUMBER, msg_type='image'))
        self.assertEqual(resp.status_code, 200)
        urlopen.assert_not_called()
        record = InboundWhatsAppMessage.objects.get()
        self.assertEqual(record.status, InboundWhatsAppMessage.STATUS_IGNORED)

    # ── ignored senders ────────────────────────────────────────

    def test_unknown_number_is_ignored_and_not_answered(self):
        self._open_ticket()
        with mock.patch(MOCK_URL) as urlopen:
            resp = self._post(wa_payload('w-unknown', OTHER_NUMBER, 'hi'))
        self.assertEqual(resp.status_code, 200)
        urlopen.assert_not_called()
        self.assertEqual(TicketReply.objects.count(), 0)
        self.assertEqual(InboundWhatsAppMessage.objects.get().status, InboundWhatsAppMessage.STATUS_IGNORED)

    def test_unapproved_partner_is_ignored(self):
        self.partner_profile.is_approved = False
        self.partner_profile.save()
        self._open_ticket()
        with mock.patch(MOCK_URL) as urlopen:
            self._post(wa_payload('w-unap', PARTNER_NUMBER, 'hi'))
        urlopen.assert_not_called()
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_non_opted_in_partner_is_ignored(self):
        self.partner_profile.whatsapp_opt_in = False
        self.partner_profile.save()
        self._open_ticket()
        with mock.patch(MOCK_URL) as urlopen:
            self._post(wa_payload('w-noopt', PARTNER_NUMBER, 'hi'))
        urlopen.assert_not_called()
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_no_open_ticket_replies_once(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'messages': [{'id': 'o1'}]})) as urlopen:
            resp = self._post(wa_payload('w-noticket', PARTNER_NUMBER, 'hi'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(TicketReply.objects.count(), 0)
        self.assertEqual(urlopen.call_count, 1)
        sent = json.loads(urlopen.call_args.args[0].data.decode('utf-8'))
        self.assertEqual(sent['to'], '919876543210')
        self.assertIn('No open ticket', sent['text']['body'])
        record = InboundWhatsAppMessage.objects.get()
        self.assertEqual(record.status, InboundWhatsAppMessage.STATUS_IGNORED)

    def test_no_open_ticket_respects_daily_limit(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'messages': [{'id': 'o2'}]})) as urlopen:
            with override_settings(NOTIFY_WHATSAPP_DAILY_LIMIT=1):
                self._post(wa_payload('w-l1', PARTNER_NUMBER, 'a'))
                urlopen.reset_mock()
                self._post(wa_payload('w-l2', PARTNER_NUMBER, 'b'))
        urlopen.assert_not_called()  # second message hit the daily limit

    # ── opt-out / opt-in ───────────────────────────────────────

    def test_stop_opts_out_and_replies_once(self):
        with mock.patch(MOCK_URL, return_value=FakeResponse({'messages': [{'id': 'o3'}]})) as urlopen:
            self._post(wa_payload('w-stop', PARTNER_NUMBER, 'STOP'))
        self.partner_profile.refresh_from_db()
        self.assertFalse(self.partner_profile.whatsapp_opt_in)
        self.assertFalse(self.partner_profile.notify_whatsapp)
        self.assertEqual(self.partner_profile.whatsapp_number, PARTNER_NUMBER)  # number kept
        self.assertEqual(urlopen.call_count, 1)
        sent = json.loads(urlopen.call_args.args[0].data.decode('utf-8'))
        self.assertIn('no longer receive', sent['text']['body'])

    def test_start_reenables_notify_when_still_opted_in(self):
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.notify_whatsapp = False
        self.partner_profile.save()
        with mock.patch(MOCK_URL) as urlopen:
            self._post(wa_payload('w-start', PARTNER_NUMBER, 'START'))
        self.partner_profile.refresh_from_db()
        self.assertTrue(self.partner_profile.whatsapp_opt_in)
        self.assertTrue(self.partner_profile.notify_whatsapp)
        urlopen.assert_not_called()

    def test_start_does_nothing_when_opted_out(self):
        self.partner_profile.whatsapp_opt_in = False
        self.partner_profile.notify_whatsapp = False
        self.partner_profile.save()
        self._post(wa_payload('w-start2', PARTNER_NUMBER, 'START'))
        self.partner_profile.refresh_from_db()
        self.assertFalse(self.partner_profile.notify_whatsapp)

    # ── staff visibility ───────────────────────────────────────

    def test_whatsapp_reply_appears_in_staff_feed(self):
        ticket = self._open_ticket()
        self._post(wa_payload('w-feed', PARTNER_NUMBER, 'from whatsapp'))
        self.login_as(self.staff)
        resp = self.client.get(reverse('notifications_feed'))
        data = resp.json()
        titles = [n['title'] for n in data['notifications']]
        self.assertIn(ticket.subject, titles)


# =================================================================
# Webhook registration command
# =================================================================

@override_settings(**D360_SETTINGS)
class D360SetWebhookCommandTests(SimpleTestCase):

    def test_registers_webhook_with_right_body(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['request'] = request
            return FakeResponse({})

        url = 'https://portal.example.com/webhooks/whatsapp/' + WEBHOOK_TOKEN + '/'
        with mock.patch(MOCK_URL, side_effect=fake_urlopen):
            call_command('d360_set_webhook', url)

        request = captured['request']
        self.assertEqual(request.full_url, BASE_URL + '/v1/configs/webhook')
        self.assertEqual(request.get_header('D360-api-key'), API_KEY)
        self.assertEqual(json.loads(request.data.decode('utf-8')), {'url': url})

    def test_rejects_non_https_url(self):
        with self.assertRaises(CommandError):
            call_command('d360_set_webhook', 'http://insecure.example.com/hook/')

    @override_settings(D360_API_KEY='')
    def test_requires_api_key(self):
        with self.assertRaises(CommandError):
            call_command('d360_set_webhook', 'https://portal.example.com/hook/')
