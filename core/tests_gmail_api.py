"""Tests for the Gmail API email backend (phase 6).

Covers GmailAPIEmailBackend (OAuth token refresh and caching, MIME building,
HTTP errors, fail_silently, secret redaction), the EMAIL_PROVIDER setting and
send_test_email with the Gmail backend.

Every HTTP call is mocked: these tests never touch the network.
"""

import base64
import email
import email.policy
import io
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from core import email_backends
from core.email_backends import GmailAPIEmailBackend, GmailAPIError

CLIENT_ID = 'test-client-id.apps.googleusercontent.com'
CLIENT_SECRET = 'GOCSPX-test-client-secret-not-real'
REFRESH_TOKEN = '1//test-refresh-token-not-real'
ACCESS_TOKEN = 'ya29.test-access-token-not-real'

GMAIL_ON = {
    'EMAIL_BACKEND': 'core.email_backends.GmailAPIEmailBackend',
    'GMAIL_CLIENT_ID': CLIENT_ID,
    'GMAIL_CLIENT_SECRET': CLIENT_SECRET,
    'GMAIL_REFRESH_TOKEN': REFRESH_TOKEN,
    'GMAIL_SENDER': 'portal@gmail.com',
    'DEFAULT_FROM_EMAIL': 'Partner Portal <portal@gmail.com>',
}

POST = 'core.email_backends.requests.post'


def fake_response(status_code=200, json_data=None, text=''):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = json_data if json_data is not None else {}
    return response


def token_response(token=ACCESS_TOKEN, expires_in=3599):
    return fake_response(200, {'access_token': token, 'expires_in': expires_in, 'token_type': 'Bearer'})


def sent_response():
    return fake_response(200, {'id': '18c0abc', 'labelIds': ['SENT']})


def route(token=None, send=None):
    """side_effect for requests.post that answers by URL."""
    token = token or [token_response()]
    send = send or [sent_response()]

    def _post(url, **kwargs):
        queue = token if url == email_backends.GMAIL_TOKEN_URL else send
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item
    return _post


def calls_to(post_mock, url):
    return [c for c in post_mock.call_args_list if c.args[0] == url]


@override_settings(**GMAIL_ON)
class GmailBackendTestBase(SimpleTestCase):

    def setUp(self):
        email_backends._reset_gmail_token_cache()
        self.addCleanup(email_backends._reset_gmail_token_cache)

    def _message(self, **kwargs):
        message = EmailMultiAlternatives(
            subject=kwargs.get('subject', 'Your lead was updated'),
            body='Plain text version.',
            from_email='Partner Portal <portal@gmail.com>',
            to=['partner@example.com'],
            cc=kwargs.get('cc', []),
            bcc=kwargs.get('bcc', []),
            reply_to=kwargs.get('reply_to', []),
        )
        if kwargs.get('html', True):
            message.attach_alternative('<p>HTML version.</p>', 'text/html')
        return message

    def _decoded_raw(self, post_mock):
        send_call = calls_to(post_mock, email_backends.GMAIL_SEND_URL)[-1]
        raw = send_call.kwargs['json']['raw']
        return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=email.policy.default)


class GmailTokenTests(GmailBackendTestBase):

    def test_token_refresh_posts_refresh_token_grant(self):
        with mock.patch(POST, side_effect=route()) as post:
            GmailAPIEmailBackend().send_messages([self._message()])

        token_calls = calls_to(post, email_backends.GMAIL_TOKEN_URL)
        self.assertEqual(len(token_calls), 1)
        self.assertEqual(token_calls[0].kwargs['data'], {
            'grant_type': 'refresh_token',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': REFRESH_TOKEN,
        })
        self.assertEqual(token_calls[0].kwargs['timeout'], 10)

    def test_access_token_is_cached_and_reused(self):
        with mock.patch(POST, side_effect=route()) as post:
            backend = GmailAPIEmailBackend()
            backend.send_messages([self._message()])
            backend.send_messages([self._message()])
            GmailAPIEmailBackend().send_messages([self._message(), self._message()])

        self.assertEqual(len(calls_to(post, email_backends.GMAIL_TOKEN_URL)), 1)
        self.assertEqual(len(calls_to(post, email_backends.GMAIL_SEND_URL)), 4)

    def test_token_refreshed_within_60_seconds_of_expiry(self):
        tokens = [token_response('first-token', 3600), token_response('second-token', 3600)]
        with mock.patch(POST, side_effect=route(token=tokens)) as post:
            GmailAPIEmailBackend().send_messages([self._message()])
            # 3545s later the token has 55s left: inside the 60s margin.
            with mock.patch('core.email_backends.time.time', return_value=time.time() + 3545):
                GmailAPIEmailBackend().send_messages([self._message()])

        self.assertEqual(len(calls_to(post, email_backends.GMAIL_TOKEN_URL)), 2)
        last_send = calls_to(post, email_backends.GMAIL_SEND_URL)[-1]
        self.assertEqual(last_send.kwargs['headers']['Authorization'], 'Bearer second-token')

    def test_token_still_valid_outside_margin_is_reused(self):
        with mock.patch(POST, side_effect=route()) as post:
            GmailAPIEmailBackend().send_messages([self._message()])
            with mock.patch('core.email_backends.time.time', return_value=time.time() + 3000):
                GmailAPIEmailBackend().send_messages([self._message()])
        self.assertEqual(len(calls_to(post, email_backends.GMAIL_TOKEN_URL)), 1)

    def test_token_refresh_rejected_raises_with_status(self):
        bad = fake_response(400, text='{"error": "invalid_grant", "error_description": "Token has been expired or revoked."}')
        with mock.patch(POST, side_effect=route(token=[bad])) as post:
            with self.assertLogs('core.email_backends', level='ERROR') as captured:
                with self.assertRaises(GmailAPIError) as ctx:
                    GmailAPIEmailBackend().send_messages([self._message()])

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('invalid_grant', str(ctx.exception))
        self.assertIn('400', '\n'.join(captured.output))
        self.assertEqual(calls_to(post, email_backends.GMAIL_SEND_URL), [])

    def test_unauthorised_send_refreshes_token_once_and_retries(self):
        tokens = [token_response('stale-token'), token_response('fresh-token')]
        sends = [fake_response(401, text='{"error": {"code": 401}}'), sent_response()]
        with mock.patch(POST, side_effect=route(token=tokens, send=sends)) as post:
            sent = GmailAPIEmailBackend().send_messages([self._message()])

        self.assertEqual(sent, 1)
        self.assertEqual(len(calls_to(post, email_backends.GMAIL_TOKEN_URL)), 2)
        last_send = calls_to(post, email_backends.GMAIL_SEND_URL)[-1]
        self.assertEqual(last_send.kwargs['headers']['Authorization'], 'Bearer fresh-token')

    @override_settings(GMAIL_REFRESH_TOKEN='')
    def test_missing_credentials_raise_improperly_configured(self):
        with mock.patch(POST) as post:
            with self.assertRaises(ImproperlyConfigured) as ctx:
                GmailAPIEmailBackend().send_messages([self._message()])
        self.assertIn('GMAIL_REFRESH_TOKEN', str(ctx.exception))
        post.assert_not_called()


class GmailSendTests(GmailBackendTestBase):

    def test_successful_send_returns_count_and_posts_raw_message(self):
        with mock.patch(POST, side_effect=route()) as post:
            sent = GmailAPIEmailBackend().send_messages([self._message(), self._message()])

        self.assertEqual(sent, 2)
        send_call = calls_to(post, email_backends.GMAIL_SEND_URL)[0]
        self.assertEqual(send_call.args[0], 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send')
        self.assertEqual(send_call.kwargs['headers']['Authorization'], 'Bearer ' + ACCESS_TOKEN)
        self.assertEqual(send_call.kwargs['timeout'], 10)
        self.assertEqual(set(send_call.kwargs['json']), {'raw'})

    def test_mime_includes_text_html_cc_bcc_reply_to_and_attachment(self):
        message = self._message(
            subject='Commission statement',
            cc=['manager@example.com'],
            bcc=['audit@example.com', 'archive@example.com'],
            reply_to=['support@example.com'],
        )
        message.attach('statement.csv', 'lead,amount\nA,100\n', 'text/csv')

        with mock.patch(POST, side_effect=route()) as post:
            GmailAPIEmailBackend().send_messages([message])

        parsed = self._decoded_raw(post)
        self.assertEqual(parsed['Subject'], 'Commission statement')
        self.assertEqual(parsed['From'], 'Partner Portal <portal@gmail.com>')
        self.assertEqual(parsed['To'], 'partner@example.com')
        self.assertEqual(parsed['Cc'], 'manager@example.com')
        self.assertEqual(parsed['Bcc'], 'audit@example.com, archive@example.com')
        self.assertEqual(parsed['Reply-To'], 'support@example.com')

        self.assertEqual(parsed.get_body(preferencelist=('plain',)).get_content().strip(), 'Plain text version.')
        self.assertEqual(parsed.get_body(preferencelist=('html',)).get_content().strip(), '<p>HTML version.</p>')
        attachments = list(parsed.iter_attachments())
        self.assertEqual([a.get_filename() for a in attachments], ['statement.csv'])
        self.assertIn('A,100', attachments[0].get_content())

    def test_raw_is_base64url_without_standard_alphabet(self):
        with mock.patch(POST, side_effect=route()) as post:
            GmailAPIEmailBackend().send_messages([self._message(subject='?>?>?>' * 20)])
        raw = calls_to(post, email_backends.GMAIL_SEND_URL)[0].kwargs['json']['raw']
        self.assertNotIn('+', raw)
        self.assertNotIn('/', raw)

    def test_plain_text_only_message(self):
        with mock.patch(POST, side_effect=route()) as post:
            GmailAPIEmailBackend().send_messages([self._message(html=False)])
        parsed = self._decoded_raw(post)
        self.assertEqual(parsed.get_content_type(), 'text/plain')
        self.assertIn('Plain text version.', parsed.get_content())

    def test_message_without_recipients_is_skipped(self):
        message = self._message()
        message.to = []
        with mock.patch(POST) as post:
            self.assertEqual(GmailAPIEmailBackend().send_messages([message]), 0)
        post.assert_not_called()

    def test_empty_list_returns_zero(self):
        self.assertEqual(GmailAPIEmailBackend().send_messages([]), 0)

    def test_http_error_logs_status_and_excerpt_and_raises(self):
        body = '{"error": {"code": 403, "message": "Request had insufficient authentication scopes."}}'
        with mock.patch(POST, side_effect=route(send=[fake_response(403, text=body)])):
            with self.assertLogs('core.email_backends', level='ERROR') as captured:
                with self.assertRaises(GmailAPIError) as ctx:
                    GmailAPIEmailBackend().send_messages([self._message()])

        output = '\n'.join(captured.output)
        self.assertIn('HTTP 403', output)
        self.assertIn('insufficient authentication scopes', output)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_error_excerpt_is_short(self):
        body = 'x' * 5000
        with mock.patch(POST, side_effect=route(send=[fake_response(500, text=body)])):
            with self.assertLogs('core.email_backends', level='ERROR') as captured:
                with self.assertRaises(GmailAPIError):
                    GmailAPIEmailBackend().send_messages([self._message()])
        self.assertLess(len(captured.records[0].getMessage()), 400)

    def test_network_error_raises_gmail_error(self):
        error = requests.ConnectionError('connection reset')
        with mock.patch(POST, side_effect=route(send=[error])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                with self.assertRaises(GmailAPIError):
                    GmailAPIEmailBackend().send_messages([self._message()])

    def test_fail_silently_swallows_http_errors(self):
        with mock.patch(POST, side_effect=route(send=[fake_response(500, text='backend error')])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                sent = GmailAPIEmailBackend(fail_silently=True).send_messages([self._message()])
        self.assertEqual(sent, 0)

    def test_fail_silently_swallows_token_and_network_errors(self):
        with mock.patch(POST, side_effect=route(token=[requests.Timeout('timed out')])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                sent = GmailAPIEmailBackend(fail_silently=True).send_messages([self._message()])
        self.assertEqual(sent, 0)

    @override_settings(GMAIL_CLIENT_SECRET='')
    def test_fail_silently_swallows_missing_configuration(self):
        self.assertEqual(GmailAPIEmailBackend(fail_silently=True).send_messages([self._message()]), 0)

    def test_fail_silently_counts_only_successful_messages(self):
        sends = [sent_response(), fake_response(500, text='oops'), sent_response()]
        with mock.patch(POST, side_effect=route(send=sends)):
            with self.assertLogs('core.email_backends', level='ERROR'):
                sent = GmailAPIEmailBackend(fail_silently=True).send_messages(
                    [self._message(), self._message(), self._message()])
        self.assertEqual(sent, 2)

    def test_without_fail_silently_errors_propagate(self):
        with mock.patch(POST, side_effect=route(send=[fake_response(500, text='oops')])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                with self.assertRaises(GmailAPIError):
                    GmailAPIEmailBackend(fail_silently=False).send_messages([self._message()])


class GmailSecretRedactionTests(GmailBackendTestBase):
    """Neither the client secret, refresh token nor access token is ever logged."""

    SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN)

    def assertNoSecrets(self, text):
        for secret in self.SECRETS:
            self.assertNotIn(secret, text)

    def test_success_path_logs_no_secrets(self):
        with mock.patch(POST, side_effect=route()):
            with self.assertLogs('core.email_backends', level='DEBUG') as captured:
                GmailAPIEmailBackend().send_messages([self._message()])
        self.assertNoSecrets('\n'.join(captured.output))

    def test_token_error_echoing_secrets_is_redacted(self):
        body = 'bad client_secret={} refresh_token={}'.format(CLIENT_SECRET, REFRESH_TOKEN)
        with mock.patch(POST, side_effect=route(token=[fake_response(401, text=body)])):
            with self.assertLogs('core.email_backends', level='DEBUG') as captured:
                with self.assertRaises(GmailAPIError) as ctx:
                    GmailAPIEmailBackend().send_messages([self._message()])
        self.assertNoSecrets('\n'.join(captured.output))
        self.assertNoSecrets(str(ctx.exception))
        self.assertIn('[redacted]', '\n'.join(captured.output))

    def test_send_error_echoing_access_token_is_redacted(self):
        body = 'invalid header Authorization: Bearer {}'.format(ACCESS_TOKEN)
        with mock.patch(POST, side_effect=route(send=[fake_response(400, text=body)])):
            with self.assertLogs('core.email_backends', level='DEBUG') as captured:
                with self.assertRaises(GmailAPIError) as ctx:
                    GmailAPIEmailBackend().send_messages([self._message()])
        self.assertNoSecrets('\n'.join(captured.output))
        self.assertNoSecrets(str(ctx.exception))

    def test_network_error_echoing_secret_is_redacted(self):
        error = requests.ConnectionError('failed for refresh_token={}'.format(REFRESH_TOKEN))
        with mock.patch(POST, side_effect=route(token=[error])):
            with self.assertLogs('core.email_backends', level='DEBUG') as captured:
                sent = GmailAPIEmailBackend(fail_silently=True).send_messages([self._message()])
        self.assertEqual(sent, 0)
        self.assertNoSecrets('\n'.join(captured.output))

    def test_send_test_email_error_contains_no_secrets(self):
        body = 'echo {} {}'.format(ACCESS_TOKEN, CLIENT_SECRET)
        with mock.patch(POST, side_effect=route(send=[fake_response(403, text=body)])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                with self.assertRaises(CommandError) as ctx:
                    call_command('send_test_email', 'someone@example.com', stdout=io.StringIO())
        self.assertNoSecrets(str(ctx.exception))
        self.assertIn('HTTP 403', str(ctx.exception))


class SendTestEmailGmailTests(GmailBackendTestBase):

    def test_command_reports_success_and_gmail_sender(self):
        out = io.StringIO()
        with mock.patch(POST, side_effect=route()):
            call_command('send_test_email', 'someone@example.com', stdout=out)
        text = out.getvalue()
        self.assertIn('GmailAPIEmailBackend', text)
        self.assertIn('From:    portal@gmail.com', text)
        self.assertIn('Success', text)

    def test_command_prints_exact_error(self):
        bad = fake_response(400, text='{"error": "invalid_grant"}')
        with mock.patch(POST, side_effect=route(token=[bad])):
            with self.assertLogs('core.email_backends', level='ERROR'):
                with self.assertRaises(CommandError) as ctx:
                    call_command('send_test_email', 'someone@example.com', stdout=io.StringIO())
        message = str(ctx.exception)
        self.assertIn('GmailAPIError', message)
        self.assertIn('HTTP 400', message)
        self.assertIn('invalid_grant', message)


class EmailProviderSettingTests(SimpleTestCase):
    """EMAIL_PROVIDER is read at import time, so settings load in a subprocess."""

    BASE_DIR = Path(__file__).resolve().parent.parent

    def _settings(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('EMAIL_', 'BREVO_', 'GMAIL_'))}
        clean.pop('DEFAULT_FROM_EMAIL', None)
        clean.update({'DJANGO_DEBUG': 'True', 'DJANGO_SETTINGS_MODULE': 'config.settings'})
        clean.update(env)
        code = (
            'from django.conf import settings as s; '
            'print(s.EMAIL_BACKEND); print(s.DEFAULT_FROM_EMAIL)'
        )
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=self.BASE_DIR, env=clean,
            capture_output=True, text=True, timeout=60,
        )
        return result

    def test_default_keeps_current_behaviour(self):
        result = self._settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('django.core.mail.backends.console.EmailBackend', result.stdout)

    def test_brevo_key_without_provider_still_selects_brevo(self):
        result = self._settings(BREVO_API_KEY='brevo-key-not-real')
        self.assertIn('core.email_backends.BrevoAPIEmailBackend', result.stdout)

    def test_gmail_api_provider(self):
        result = self._settings(
            EMAIL_PROVIDER='gmail_api', GMAIL_SENDER='portal@gmail.com', BREVO_API_KEY='brevo-key-not-real')
        backend, from_email = result.stdout.strip().splitlines()
        self.assertEqual(backend, 'core.email_backends.GmailAPIEmailBackend')
        self.assertEqual(from_email, 'Partner Portal <portal@gmail.com>')

    def test_console_provider(self):
        result = self._settings(EMAIL_PROVIDER='console', BREVO_API_KEY='brevo-key-not-real')
        self.assertIn('django.core.mail.backends.console.EmailBackend', result.stdout)

    def test_invalid_provider_is_rejected(self):
        result = self._settings(EMAIL_PROVIDER='sendgrid')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('EMAIL_PROVIDER', result.stderr)
