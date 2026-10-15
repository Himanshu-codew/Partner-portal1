"""OCR helper service: the /internal/ocr/ endpoint, worker-only mode and the
RemoteOCRProvider that the main portal uses to call it.

No network: ``requests.post`` is mocked (in the end-to-end tests it is routed
into the Django test client), and Tesseract itself is mocked.
"""

import json
import logging
from unittest import mock

import requests
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.services import ocr
from core.services.ocr import HybridProvider, OCRResult, RemoteOCRProvider, get_provider, process_document
from core.tests import BaseTestCase
from core.tests_phase3 import KEY, FakeOCRResponse, make_document, ocr_payload

TOKEN = 'helper-token-0123456789abcdef-not-real'
URL = 'https://ocr-helper.example.com'
ENDPOINT = URL + '/internal/ocr/'
POST = 'core.services.ocr.requests.post'
GET = 'core.services.ocr.requests.get'
EXTRACT = 'core.services.ocr.TesseractProvider.extract_text'
LONG_TEXT = 'INCOME TAX DEPARTMENT Permanent Account Number ABCDE1234F'


def fake_response(status_code=200, payload=None, text=None):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text if text is not None else json.dumps(payload or {})
    if payload is not None:
        response.json.return_value = payload
    else:
        response.json.side_effect = ValueError('not json')
    return response


def route_to(client):
    """requests.post stand-in that delivers the request to the Django test client."""

    def _get(url, timeout=None):
        response = client.get(url.replace(URL, ''))
        return fake_response(response.status_code, json.loads(response.content or b'{}'))

    def _post(url, files=None, headers=None, timeout=None):
        name, content, content_type = files['file']
        response = client.post(
            url.replace(URL, ''),
            {'file': SimpleUploadedFile(name, content, content_type=content_type)},
            HTTP_AUTHORIZATION=headers.get('Authorization', ''),
        )
        return fake_response(response.status_code, json.loads(response.content or b'{}'))
    return _get, _post


def routed(client):
    """Patch requests.get/post so the helper calls reach the Django test client."""
    _get, _post = route_to(client)
    return mock.patch(GET, side_effect=_get), mock.patch(POST, side_effect=_post)


# =================================================================
# Helper endpoint
# =================================================================

@override_settings(OCR_WORKER_TOKEN=TOKEN, OCR_WORKER_ONLY=False)
class OCRWorkerEndpointTests(TestCase):

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def post(self, token=TOKEN, file=True, **extra):
        data = {'file': SimpleUploadedFile('scan.png', b'\x89PNG data', content_type='image/png')} if file else {}
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token is not None else {}
        return self.client.post('/internal/ocr/', data, **headers, **extra)

    @override_settings(OCR_WORKER_TOKEN='')
    def test_endpoint_does_not_exist_without_token(self):
        self.assertEqual(self.client.get('/internal/ocr/').status_code, 404)
        self.assertEqual(self.post(token='anything').status_code, 404)

    @override_settings(OCR_WORKER_TOKEN='short-token')
    def test_short_token_disables_endpoint(self):
        self.assertEqual(self.post(token='short-token').status_code, 404)

    @mock.patch('core.views.shutil.which', return_value='/usr/bin/tesseract')
    def test_get_reports_readiness_without_secrets(self, which):
        response = self.client.get('/internal/ocr/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ready', 'tesseract': True})
        self.assertNotIn(TOKEN, response.content.decode())

    @mock.patch(EXTRACT)
    def test_missing_or_wrong_token_is_rejected(self, extract):
        self.assertEqual(self.post(token=None).status_code, 401)
        self.assertEqual(self.post(token='wrong-token-0123456789abcdef').status_code, 401)
        self.assertEqual(self.post(token=TOKEN + 'x').status_code, 401)
        extract.assert_not_called()

    @mock.patch(EXTRACT, return_value=OCRResult(True, LONG_TEXT, '', 'tesseract'))
    def test_runs_tesseract_and_returns_json_without_csrf_token(self, extract):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'text': LONG_TEXT, 'error': ''})
        args = extract.call_args.args
        self.assertEqual(args, (b'\x89PNG data', 'scan.png', 'image/png'))

    @mock.patch(EXTRACT, return_value=OCRResult(False, '', 'tesseract timed out after 120s', 'tesseract'))
    def test_tesseract_failure_is_reported(self, extract):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ok'], False)
        self.assertIn('timed out', response.json()['error'])

    @mock.patch(EXTRACT)
    def test_missing_file_is_bad_request(self, extract):
        self.assertEqual(self.post(file=False).status_code, 400)
        extract.assert_not_called()

    @override_settings(OCR_WORKER_MAX_BYTES=4)
    @mock.patch(EXTRACT)
    def test_file_too_large(self, extract):
        self.assertEqual(self.post().status_code, 413)
        extract.assert_not_called()

    def test_other_methods_not_allowed(self):
        self.assertEqual(self.client.put('/internal/ocr/').status_code, 405)

    @mock.patch(EXTRACT, return_value=OCRResult(True, 'Aadhaar 1234 5678 9012 secret text', '', 'tesseract'))
    def test_extracted_text_is_not_logged(self, extract):
        with self.assertLogs('core.ocr', level=logging.DEBUG) as captured:
            self.post()
        self.assertNotIn('1234 5678 9012', '\n'.join(captured.output))
        self.assertNotIn(TOKEN, '\n'.join(captured.output))


@override_settings(OCR_WORKER_TOKEN=TOKEN, OCR_WORKER_ONLY=True)
class OCRWorkerOnlyModeTests(TestCase):

    def test_every_other_page_is_hidden(self):
        for path in ('/', '/admin/', '/login/', '/partners/', '/manifest.webmanifest', '/static/css/portal.css'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    @mock.patch('core.views.shutil.which', return_value=None)
    def test_ocr_endpoint_still_reachable(self, which):
        self.assertEqual(self.client.get('/internal/ocr/').status_code, 200)

    @override_settings(OCR_WORKER_ONLY=False)
    def test_off_by_default_pages_work(self):
        self.assertNotEqual(self.client.get('/login/').status_code, 404)


# =================================================================
# RemoteOCRProvider (main portal side)
# =================================================================

class RemoteOCRProviderTests(SimpleTestCase):

    def setUp(self):
        sleep = mock.patch('core.services.ocr.time.sleep')
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        get = mock.patch(GET, return_value=fake_response(200, {'status': 'ready', 'tesseract': True}))
        self.get = get.start()
        self.addCleanup(get.stop)
        self.provider = RemoteOCRProvider(URL + '/', TOKEN, timeout=300)

    def test_not_configured_makes_no_request(self):
        with mock.patch(POST) as post:
            result = RemoteOCRProvider('', TOKEN).extract_text(b'img', 'scan.png', 'image/png')
            result2 = RemoteOCRProvider(URL, '').extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertFalse(result2.ok)
        self.assertIn('not configured', result.error)
        post.assert_not_called()

    def test_success_posts_file_with_bearer_token(self):
        response = fake_response(200, {'ok': True, 'text': LONG_TEXT, 'error': ''})
        with mock.patch(POST, return_value=response) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')

        self.assertTrue(result.ok)
        self.assertEqual(result.text, LONG_TEXT)
        self.assertEqual(result.provider, 'remote')
        self.assertEqual(post.call_args.args[0], ENDPOINT)
        self.assertEqual(post.call_args.kwargs['headers'], {'Authorization': f'Bearer {TOKEN}'})
        self.assertEqual(post.call_args.kwargs['files'], {'file': ('scan.png', b'img', 'image/png')})
        self.assertEqual(post.call_args.kwargs['timeout'], (15, 300))
        self.sleep.assert_not_called()

    def test_helper_reported_failure(self):
        response = fake_response(200, {'ok': False, 'text': '', 'error': 'Tesseract is not installed on this server'})
        with mock.patch(POST, return_value=response):
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('not installed', result.error)

    def test_sleeping_helper_is_woken_before_upload(self):
        self.get.side_effect = [fake_response(502, text='<!DOCTYPE html>'),
                                requests.ConnectionError('waking'),
                                fake_response(200, {'status': 'ready'})]
        response = fake_response(200, {'ok': True, 'text': LONG_TEXT, 'error': ''})
        with mock.patch(POST, return_value=response) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual(self.get.call_args.args[0], ENDPOINT)
        self.assertEqual(post.call_count, 1)

    def test_upload_is_still_tried_when_helper_never_wakes(self):
        self.get.return_value = fake_response(503, text='<html>')
        with mock.patch(POST, return_value=fake_response(200, {'ok': True, 'text': LONG_TEXT})) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(self.get.call_count, RemoteOCRProvider.WAKE_ATTEMPTS)
        post.assert_called_once()

    def test_unavailable_helper_is_retried(self):
        responses = [fake_response(502, text='<!DOCTYPE html>'),
                     fake_response(503, text='Service Unavailable'),
                     fake_response(200, {'ok': True, 'text': LONG_TEXT, 'error': ''})]
        with mock.patch(POST, side_effect=responses) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(post.call_count, 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [15, 30])

    def test_unavailable_error_has_no_html(self):
        page = '<!DOCTYPE html> <html lang="en"> <head> <title>502</title>'
        with mock.patch(POST, return_value=fake_response(502, text=page)) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertEqual(post.call_count, 3)
        self.assertIn('OCR helper HTTP 502', result.error)
        self.assertIn('Retry OCR', result.error)
        self.assertNotIn('<', result.error)

    def test_connection_error_is_retried_then_fails(self):
        with mock.patch(POST, side_effect=requests.ConnectionError(f'refused {TOKEN}')) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertEqual(post.call_count, 3)
        self.assertIn('ConnectionError', result.error)
        self.assertNotIn(TOKEN, result.error)

    def test_read_timeout_is_not_retried(self):
        with mock.patch(POST, side_effect=requests.ReadTimeout('slow')) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertEqual(post.call_count, 1)
        self.assertIn('ReadTimeout', result.error)

    def test_unauthorised_is_not_retried(self):
        with mock.patch(POST, return_value=fake_response(401, {'ok': False, 'error': 'unauthorized'})) as post:
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('HTTP 401', result.error)
        self.assertEqual(post.call_count, 1)

    def test_non_json_response(self):
        with mock.patch(POST, return_value=fake_response(200, text='<html>')):
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('non-JSON', result.error)

    def test_html_error_page_body_is_dropped(self):
        with mock.patch(POST, return_value=fake_response(404, text='<!DOCTYPE html><title>Not Found</title>')):
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertEqual(result.error, 'OCR helper HTTP 404')

    @override_settings(OCR_WORKER_TOKEN=TOKEN)
    def test_token_is_redacted_from_errors(self):
        body = f'bad token {TOKEN}'
        with mock.patch(POST, return_value=fake_response(500, text=body)):
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertNotIn(TOKEN, result.error)
        self.assertIn('[redacted]', result.error)

    def test_unexpected_exception_never_raises(self):
        with mock.patch(POST, side_effect=RuntimeError('boom')):
            result = self.provider.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)


class RemoteProviderSettingsTests(SimpleTestCase):

    @override_settings(OCR_ENABLED=True, OCR_PROVIDER='remote', OCR_REMOTE_URL=URL,
                       OCR_WORKER_TOKEN=TOKEN, OCR_REMOTE_TIMEOUT=200)
    def test_remote_provider_from_settings(self):
        provider = get_provider()
        self.assertIsInstance(provider, RemoteOCRProvider)
        self.assertEqual((provider.url, provider.token, provider.timeout), (URL, TOKEN, 200))

    @override_settings(OCR_ENABLED=True, OCR_PROVIDER='remote_hybrid', OCR_REMOTE_URL=URL,
                       OCR_WORKER_TOKEN=TOKEN, OCRSPACE_API_KEY=KEY)
    def test_remote_hybrid_falls_back_to_ocrspace(self):
        provider = get_provider()
        self.assertIsInstance(provider, HybridProvider)
        self.assertIsInstance(provider.local, RemoteOCRProvider)
        self.assertEqual(provider.remote.api_key, KEY)


# =================================================================
# End to end: portal -> RemoteOCRProvider -> helper endpoint -> Tesseract
# =================================================================

REMOTE_ON = {
    'OCR_ENABLED': True,
    'OCR_PROVIDER': 'remote',
    'OCR_REMOTE_URL': URL,
    'OCR_WORKER_TOKEN': TOKEN,
    'OCR_WORKER_ONLY': False,
    'OCRSPACE_API_KEY': KEY,
    'OCR_DAILY_LIMIT': 1,
    'OCR_MAX_BYTES': 16,
}


@override_settings(**REMOTE_ON)
class RemoteOCREndToEndTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()

    @mock.patch(EXTRACT, return_value=OCRResult(True, 'Aadhaar 1234 5678 9012 PAN ABCDE1234F', '', 'tesseract'))
    def test_document_is_read_by_helper_masked_and_not_metered(self, extract):
        ocr.bump_quota()  # OCR.space quota is used up; the helper is not metered
        document = make_document(self.partner_profile, content=b'\x89PNG' + b'x' * 500)

        get, post = routed(Client())
        with get, post, mock.patch('core.services.ocr.urlopen') as urlopen:
            process_document(document.pk)
        document.refresh_from_db()

        self.assertEqual(document.ocr_status, 'done', document.ocr_error)
        self.assertNotIn('1234 5678 9012', document.ocr_text)
        self.assertEqual(document.extracted.get('pan'), 'ABCDE1234F')
        self.assertEqual(len(extract.call_args.args[0]), 504)  # whole file, no 16-byte cap
        self.assertEqual(cache.get(ocr._quota_key()), 1)
        urlopen.assert_not_called()

    @override_settings(OCR_PROVIDER='remote_hybrid', OCR_DAILY_LIMIT=10, OCR_MAX_BYTES=1024 * 1024)
    @mock.patch(EXTRACT, return_value=OCRResult(False, '', 'tesseract timed out after 120s', 'tesseract'))
    def test_helper_failure_falls_back_to_ocrspace(self, extract):
        document = make_document(self.partner_profile)
        get, post = routed(Client())
        with get, post, \
                mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload(LONG_TEXT))):
            process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'done')
        self.assertIn('ABCDE1234F', document.ocr_text)

    def test_helper_down_marks_failed_without_crashing(self):
        document = make_document(self.partner_profile)
        with mock.patch(POST, side_effect=requests.ConnectionError('down')), \
                mock.patch(GET, side_effect=requests.ConnectionError('down')), \
                mock.patch('core.services.ocr.time.sleep'):
            process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertIn('OCR helper request failed', document.ocr_error)
