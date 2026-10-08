"""Phase 3 — OCR for partner KYC and invoice documents.

Every HTTP call to the OCR provider is mocked: these tests must never
touch the network, and the API key must never appear in an error, a log
line or a stored field.
"""

import io
import json
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from urllib.error import HTTPError, URLError

from core.models import NotificationLog
from core.services.extraction import extract_suggestions, mask_aadhaar
from core.services.notifications import EVENTS, build_context
from core.services.ocr import (
    OCRSpaceProvider,
    bump_quota,
    get_provider,
    process_document,
    quota_available,
)
from core.tests import BaseTestCase
from partners.forms import PartnerDocumentForm
from partners.models import PartnerDocument

KEY = 'test_ocr_key_123'
ENDPOINT = 'https://api.ocr.space/parse/image'

# Explicit settings so results do not depend on the developer's environment.
OCR_ON = {
    'OCR_ENABLED': True,
    'OCRSPACE_API_KEY': KEY,
    'OCR_PROVIDER': 'ocrspace',
    'OCR_DAILY_LIMIT': 100,
    'OCR_MAX_BYTES': 1024 * 1024,
}
OCR_OFF = {'OCR_ENABLED': False, 'OCRSPACE_API_KEY': KEY}


class FakeOCRResponse:
    """Stand-in for the object urlopen() returns."""

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def ocr_payload(text, error=''):
    return json.dumps({
        'ParsedResults': [{'ParsedText': text}],
        'IsErroredOnProcessing': bool(error),
        'ErrorMessage': error,
    }).encode('utf-8')


def make_document(profile, doc_type='PAN', name='scan.png', content=None, **extra):
    defaults = {
        'doc_type': doc_type,
        'file': SimpleUploadedFile(name, content or (b'\x89PNG\r\n\x1a\n' + b'x' * 64)),
    }
    defaults.update(extra)
    return PartnerDocument.objects.create(partner=profile, **defaults)


# =================================================================
# Provider: request format, parsing, error handling, redaction
# =================================================================

@override_settings(OCR_ENABLED=True, OCRSPACE_API_KEY=KEY)
class OCRSpaceProviderTests(SimpleTestCase):

    def test_request_is_multipart_post_with_key_in_header_only(self):
        provider = OCRSpaceProvider(KEY)
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            urlopen.return_value = FakeOCRResponse(ocr_payload('hello world'))
            result = provider.extract_text(b'PNGDATA', 'scan.png', 'image/png')

        self.assertTrue(result.ok)
        self.assertEqual(result.text, 'hello world')

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, ENDPOINT)
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.assertEqual(headers['apikey'], KEY)
        self.assertTrue(headers['content-type'].startswith('multipart/form-data; boundary='))

        body = request.data
        self.assertIn(b'name="language"', body)
        self.assertIn(b'name="OCREngine"', body)
        self.assertIn(b'2\r\n', body)
        self.assertIn(b'name="isOverlayRequired"', body)
        self.assertIn(b'name="file"; filename="scan.png"', body)
        self.assertIn(b'Content-Type: image/png', body)
        self.assertIn(b'PNGDATA', body)
        # the key must never travel in the body
        self.assertNotIn(KEY.encode(), body)
        self.assertEqual(urlopen.call_args.kwargs.get('timeout'), 25)

    def test_parses_text_from_multiple_pages(self):
        payload = json.dumps({
            'ParsedResults': [{'ParsedText': 'line one'}, {'ParsedText': 'line two'}],
            'IsErroredOnProcessing': False,
            'ErrorMessage': '',
        }).encode()
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(payload)):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.pdf', 'application/pdf')
        self.assertTrue(result.ok)
        self.assertEqual(result.text, 'line one\nline two')
        self.assertEqual(result.provider, 'ocrspace')

    def test_provider_error_flag_fails_and_redacts_the_key(self):
        payload = ocr_payload('', error=f'quota exceeded for key {KEY}')
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(payload)):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('quota exceeded', result.error)
        self.assertNotIn(KEY, result.error)
        self.assertIn('[redacted]', result.error)

    def test_http_error_is_caught_and_redacted(self):
        body = io.BytesIO(json.dumps({'ErrorMessage': f'invalid key {KEY}'}).encode())
        error = HTTPError(ENDPOINT, 401, 'Unauthorized', {}, body)
        with mock.patch('core.services.ocr.urlopen', side_effect=error):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('HTTP 401', result.error)
        self.assertNotIn(KEY, result.error)

    def test_network_error_is_caught(self):
        with mock.patch(
            'core.services.ocr.urlopen', side_effect=URLError('connection refused')
        ):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('connection refused', result.error)

    def test_non_json_response_fails_cleanly(self):
        with mock.patch(
            'core.services.ocr.urlopen', return_value=FakeOCRResponse(b'<html>oops</html>')
        ):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('non-JSON', result.error)

    def test_missing_key_short_circuits_without_http(self):
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            result = OCRSpaceProvider('').extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('not configured', result.error)
        urlopen.assert_not_called()

    def test_unexpected_exception_never_raises(self):
        with mock.patch('core.services.ocr.urlopen', side_effect=RuntimeError('boom')):
            result = OCRSpaceProvider(KEY).extract_text(b'x', 'a.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('boom', result.error)


class OCRSettingsAndQuotaTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    @override_settings(**OCR_OFF)
    def test_no_provider_while_disabled(self):
        self.assertIsNone(get_provider())

    @override_settings(**OCR_ON)
    def test_provider_instance_when_enabled(self):
        provider = get_provider()
        self.assertIsInstance(provider, OCRSpaceProvider)
        self.assertEqual(provider.api_key, KEY)

    @override_settings(OCR_ENABLED=True, OCR_PROVIDER='someone-else')
    def test_unknown_provider_returns_none(self):
        self.assertIsNone(get_provider())

    @override_settings(OCR_DAILY_LIMIT=2)
    def test_quota_allows_up_to_the_limit(self):
        self.assertTrue(quota_available())
        bump_quota()
        self.assertTrue(quota_available())
        bump_quota()
        self.assertFalse(quota_available())

    @override_settings(OCR_DAILY_LIMIT=0)
    def test_non_positive_limit_means_unlimited(self):
        for _ in range(50):
            bump_quota()
        self.assertTrue(quota_available())


# =================================================================
# Extraction: regex suggestions + Aadhaar masking (pure functions)
# =================================================================

class ExtractionTests(SimpleTestCase):

    def test_pan_gst_and_ifsc(self):
        out = extract_suggestions('PAN ABCDE1234F GST 29AABCU9603R1ZV IFSC HDFC0001234', 'OTHER')
        self.assertEqual(out['pan'], 'ABCDE1234F')
        self.assertEqual(out['gst'], '29AABCU9603R1ZV')
        self.assertEqual(out['ifsc'], 'HDFC0001234')

    def test_empty_and_plain_text_yield_empty_defaults(self):
        for text in ('', 'nothing to see here'):
            out = extract_suggestions(text, 'OTHER')
            self.assertEqual(out['pan'], '')
            self.assertEqual(out['gst'], '')
            self.assertEqual(out['ifsc'], '')
            self.assertEqual(out['account_numbers'], [])
            self.assertEqual(out['invoice_numbers'], [])
            self.assertEqual(out['amount'], '')
            self.assertEqual(out['emails'], [])
            self.assertEqual(out['mobiles'], [])

    def test_invoice_number_and_grand_total(self):
        out = extract_suggestions('Invoice No. INV-2024/001\nGrand Total: Rs. 1,25,000.00', 'INVOICE')
        self.assertIn('INV-2024/001', out['invoice_numbers'])
        self.assertEqual(out['amount'], '1,25,000.00')

    def test_other_total_labels(self):
        self.assertEqual(extract_suggestions('Amount Payable: 4,500', 'INVOICE')['amount'], '4,500')
        self.assertEqual(extract_suggestions('Total: 999.50', 'INVOICE')['amount'], '999.50')

    def test_bill_labels_without_digits_are_not_invoice_numbers(self):
        out = extract_suggestions('Bill To: Acme Corp', 'INVOICE')
        self.assertEqual(out['invoice_numbers'], [])

    def test_emails_and_mobiles(self):
        text = 'mail accounts@example.com or sales@site.co.in, call 9876543210 or 8123456789'
        out = extract_suggestions(text, 'OTHER')
        self.assertEqual(out['emails'], ['accounts@example.com', 'sales@site.co.in'])
        self.assertEqual(out['mobiles'], ['9876543210', '8123456789'])

    def test_account_numbers_only_for_bank_documents(self):
        text = 'Account number 1234567890123456'
        self.assertEqual(extract_suggestions(text, 'BANK')['account_numbers'], ['1234567890123456'])
        self.assertEqual(extract_suggestions(text, 'OTHER')['account_numbers'], [])

    def test_short_digit_runs_are_never_accounts(self):
        self.assertEqual(extract_suggestions('ref 12345678', 'BANK')['account_numbers'], [])

    def test_mask_handles_contiguous_and_grouped_aadhaar(self):
        self.assertEqual(mask_aadhaar('X 498765432105 Y'), 'X XXXX XXXX 2105 Y')
        self.assertEqual(mask_aadhaar('4987 6543 2105'), 'XXXX XXXX 2105')
        self.assertEqual(mask_aadhaar('4987-6543-2105'), 'XXXX XXXX 2105')

    def test_mask_tolerates_empty_input(self):
        self.assertEqual(mask_aadhaar(''), '')
        self.assertEqual(mask_aadhaar(None), '')

    def test_aadhaar_never_surfaces_in_suggestions(self):
        out = extract_suggestions('Aadhaar 4987 6543 2105, PAN ABCDE1234F', 'BANK')
        dumped = json.dumps(out)
        self.assertNotIn('498765432105', dumped)
        self.assertNotIn('6543', dumped)
        self.assertEqual(out['pan'], 'ABCDE1234F')
        self.assertEqual(out['account_numbers'], [])

    def test_pure_twelve_digit_runs_are_masked_before_extraction(self):
        out = extract_suggestions('ref 123456789012 done', 'BANK')
        self.assertEqual(out['account_numbers'], [])


# =================================================================
# Worker: background processing, gating, quota, connection handling
# =================================================================

@override_settings(**OCR_ON)
class OCRWorkerTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()

    @override_settings(**OCR_OFF)
    @mock.patch('core.services.ocr.urlopen')
    def test_disabled_marks_skipped_without_http(self, urlopen):
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'skipped')
        self.assertEqual(document.ocr_error, 'OCR is not enabled')
        urlopen.assert_not_called()

    @mock.patch('core.services.ocr.urlopen')
    def test_success_stores_masked_text_and_suggestions(self, urlopen):
        urlopen.return_value = FakeOCRResponse(ocr_payload(
            'PAN ABCDE1234F Aadhaar 498765432105 Total: 1,000.00'
        ))
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()

        self.assertEqual(document.ocr_status, 'done')
        self.assertEqual(document.ocr_error, '')
        self.assertNotIn('498765432105', document.ocr_text)
        self.assertIn('XXXX XXXX 2105', document.ocr_text)
        self.assertEqual(document.extracted['pan'], 'ABCDE1234F')
        self.assertEqual(document.extracted['amount'], '1,000.00')

    @override_settings(OCR_DAILY_LIMIT=1)
    @mock.patch('core.services.ocr.urlopen')
    def test_success_consumes_daily_quota(self, urlopen):
        urlopen.return_value = FakeOCRResponse(ocr_payload('PAN ABCDE1234F'))
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'done')
        self.assertFalse(quota_available())

    @mock.patch('core.services.ocr.urlopen')
    def test_provider_failure_marks_failed(self, urlopen):
        urlopen.side_effect = URLError('connection refused')
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertIn('connection refused', document.ocr_error)

    @mock.patch('core.services.ocr.urlopen')
    def test_api_key_never_reaches_logs_or_stored_error(self, urlopen):
        urlopen.side_effect = URLError(f'401 for {KEY}')
        document = make_document(self.partner_profile)
        with self.assertLogs('core.ocr', level='INFO') as logs:
            process_document(document.pk)
        document.refresh_from_db()
        joined = '\n'.join(logs.output)
        self.assertNotIn(KEY, joined)
        self.assertNotIn(KEY, document.ocr_error)
        self.assertIn('[redacted]', document.ocr_error)

    @mock.patch('core.services.ocr.urlopen')
    def test_garbage_provider_response_marks_failed(self, urlopen):
        urlopen.return_value = FakeOCRResponse(b'not json at all')
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertIn('non-JSON', document.ocr_error)

    @mock.patch('core.services.ocr.urlopen')
    def test_document_without_file_marks_failed(self, urlopen):
        document = PartnerDocument.objects.create(
            partner=self.partner_profile, doc_type='PAN'
        )
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertEqual(document.ocr_error, 'no file to scan')
        urlopen.assert_not_called()

    @mock.patch('core.services.ocr.urlopen')
    def test_unknown_pk_is_ignored(self, urlopen):
        process_document(999999)   # must not raise
        urlopen.assert_not_called()

    @override_settings(OCR_MAX_BYTES=16)
    @mock.patch('core.services.ocr.urlopen')
    def test_large_non_image_file_is_skipped(self, urlopen):
        document = make_document(
            self.partner_profile, name='doc.pdf', content=b'%PDF-1.4 ' + b'x' * 200
        )
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'skipped')
        self.assertEqual(document.ocr_error, 'file larger than 1 MB, enter details manually')
        urlopen.assert_not_called()

    @override_settings(OCR_MAX_BYTES=16)
    @mock.patch('core.services.ocr.urlopen')
    def test_large_image_is_downscaled_before_upload(self, urlopen):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is not installed')
        import io as byteio
        buffer = byteio.BytesIO()
        Image.new('RGB', (64, 64), color='white').save(buffer, format='PNG')

        urlopen.return_value = FakeOCRResponse(ocr_payload('ok'))
        document = make_document(
            self.partner_profile, name='big.png', content=buffer.getvalue()
        )
        process_document(document.pk)
        document.refresh_from_db()

        self.assertEqual(document.ocr_status, 'done')
        request = urlopen.call_args.args[0]
        self.assertIn(b'filename="big.jpg"', request.data)
        self.assertIn(b'Content-Type: image/jpeg', request.data)

    @override_settings(OCR_DAILY_LIMIT=1)
    @mock.patch('core.services.ocr.urlopen')
    def test_daily_limit_skips_without_http(self, urlopen):
        bump_quota()
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'skipped')
        self.assertEqual(document.ocr_error, 'daily OCR limit reached')
        urlopen.assert_not_called()

    @mock.patch('core.services.ocr.connections')
    @mock.patch('core.services.ocr.urlopen')
    def test_db_connection_is_closed_after_run(self, urlopen, connections):
        urlopen.return_value = FakeOCRResponse(ocr_payload('PAN ABCDE1234F'))
        document = make_document(self.partner_profile)
        process_document(document.pk)
        connections.__getitem__.assert_called_with('default')
        connections.__getitem__.return_value.close.assert_called()


# =================================================================
# Upload: permissions, validation, thread scheduling
# =================================================================

class KYCUploadTests(BaseTestCase):

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(reverse('kyc_document_upload'), {})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    def test_unapproved_partner_is_blocked(self):
        self.login_as(self.unapproved_user)
        response = self.client.post(reverse('kyc_document_upload'), {})
        self.assertRedirects(response, reverse('approval_pending'))
        self.assertEqual(PartnerDocument.objects.count(), 0)

    @mock.patch('partners.views.threading.Thread')
    def test_upload_stores_file_and_schedules_worker_thread(self, thread_cls):
        self.login_as(self.partner_user)
        upload = SimpleUploadedFile('pan.png', b'\x89PNG\r\n\x1a\n' + b'x' * 32)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('kyc_document_upload'),
                {'doc_type': 'PAN', 'file': upload},
            )
        self.assertRedirects(response, reverse('kyc_document_list'))

        document = PartnerDocument.objects.get()
        self.assertEqual(document.partner, self.partner_profile)
        self.assertEqual(document.doc_type, 'PAN')
        self.assertEqual(document.ocr_status, 'pending')
        self.assertTrue(document.file_exists)

        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        self.assertTrue(kwargs.get('daemon'))
        self.assertEqual(kwargs.get('args'), (document.pk,))

    @mock.patch('partners.views.threading.Thread')
    def test_second_partner_upload_belongs_to_second_partner(self, thread_cls):
        self.login_as(self.partner_user2)
        upload = SimpleUploadedFile('gst.png', b'\x89PNG\r\n\x1a\n' + b'y' * 32)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse('kyc_document_upload'),
                {'doc_type': 'GST', 'file': upload},
            )
        document = PartnerDocument.objects.get()
        self.assertEqual(document.partner, self.partner_profile2)

    def test_disallowed_extension_is_rejected(self):
        self.login_as(self.partner_user)
        upload = SimpleUploadedFile('notes.txt', b'hello')
        response = self.client.post(
            reverse('kyc_document_upload'),
            {'doc_type': 'OTHER', 'file': upload},
            follow=True,
        )
        self.assertEqual(PartnerDocument.objects.count(), 0)
        rendered = [str(message) for message in response.context['messages']]
        self.assertTrue(any('not permitted' in message for message in rendered))


class PartnerDocumentFormTests(SimpleTestCase):

    def build(self, name, size=64):
        upload = SimpleUploadedFile(name, b'x' * size)
        return PartnerDocumentForm({'doc_type': 'PAN'}, {'file': upload})

    def test_accepts_allowed_extensions(self):
        for name in ('a.pdf', 'b.jpg', 'c.jpeg', 'd.png'):
            with self.subTest(name=name):
                self.assertTrue(self.build(name).is_valid())

    def test_rejects_disallowed_extension(self):
        form = self.build('notes.txt')
        self.assertFalse(form.is_valid())
        self.assertIn('not permitted', str(form.errors['file']))

    def test_rejects_oversize_file(self):
        form = self.build('big.png', size=5 * 1024 * 1024 + 1)
        self.assertFalse(form.is_valid())
        self.assertIn('5 MB', str(form.errors['file']))


# =================================================================
# Partner list page: isolation, sidebar, upload form
# =================================================================

class KYCPartnerListTests(BaseTestCase):

    def test_unapproved_partner_cannot_open_the_page(self):
        self.login_as(self.unapproved_user)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertRedirects(response, reverse('approval_pending'))

    def test_partner_sees_only_own_documents(self):
        make_document(self.partner_profile, 'PAN')
        make_document(self.partner_profile2, 'GST')
        self.login_as(self.partner_user)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'partners/kyc_list.html')
        self.assertContains(response, 'My KYC Documents')
        self.assertContains(response, 'My KYC')          # sidebar link
        documents = list(response.context['page_obj'])
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].partner, self.partner_profile)

    def test_partner_page_shows_upload_form_and_suggestions(self):
        document = make_document(self.partner_profile, 'PAN')
        document.extracted = {'pan': 'ABCDE1234F'}
        document.ocr_status = 'done'
        document.save(update_fields=['extracted', 'ocr_status'])
        self.login_as(self.partner_user)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertContains(response, 'Upload a document')
        self.assertContains(response, 'ABCDE1234F')

    def test_partner_list_is_paginated_at_ten(self):
        for _ in range(11):
            make_document(self.partner_profile, 'OTHER')
        self.login_as(self.partner_user)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 2)
        self.assertEqual(len(response.context['page_obj']), 10)


# =================================================================
# Staff review queue: filters, search, pending badge, pagination
# =================================================================

class KYCStaffListTests(BaseTestCase):

    def test_staff_sees_review_queue_template(self):
        self.login_as(self.staff)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'partners/kyc_review_list.html')

    def test_non_staff_cannot_open_the_review_queue(self):
        self.login_as(self.partner_user)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertTemplateUsed(response, 'partners/kyc_list.html')

    def test_filters_by_review_status_type_and_company(self):
        make_document(self.partner_profile, 'PAN', review_status='pending')
        make_document(self.partner_profile2, 'GST', review_status='approved')
        self.login_as(self.staff)
        url = reverse('kyc_document_list')

        response = self.client.get(url, {'review': 'pending'})
        self.assertEqual(len(response.context['page_obj']), 1)
        response = self.client.get(url, {'review': 'approved'})
        self.assertEqual(len(response.context['page_obj']), 1)
        response = self.client.get(url, {'type': 'GST'})
        self.assertEqual(len(response.context['page_obj']), 1)
        response = self.client.get(url, {'q': 'Beta'})
        self.assertEqual(len(response.context['page_obj']), 1)
        response = self.client.get(url, {'q': 'Acme'})
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_invalid_filter_values_are_ignored(self):
        make_document(self.partner_profile, 'PAN')
        make_document(self.partner_profile2, 'GST')
        self.login_as(self.staff)
        response = self.client.get(
            reverse('kyc_document_list'), {'review': 'nonsense', 'type': 'hack'}
        )
        self.assertEqual(len(response.context['page_obj']), 2)

    def test_pending_count_in_context_and_sidebar_badge(self):
        make_document(self.partner_profile, 'PAN', review_status='pending')
        make_document(self.partner_profile, 'GST', review_status='approved')
        self.login_as(self.staff)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.context['pending_count'], 1)
        self.assertContains(response, '1 pending')
        self.assertContains(response, 'badge bg-danger rounded-pill ms-auto')

    def test_staff_queue_is_paginated_at_ten(self):
        for _ in range(11):
            make_document(self.partner_profile, 'OTHER')
        self.login_as(self.staff)
        response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 2)
        self.assertEqual(len(response.context['page_obj']), 10)

    def test_pending_count_tag(self):
        from core.templatetags.core_extras import get_kyc_pending_count
        make_document(self.partner_profile, 'PAN', review_status='pending')
        make_document(self.partner_profile, 'GST', review_status='pending')
        make_document(self.partner_profile, 'PAN', review_status='approved')
        self.assertEqual(get_kyc_pending_count(), 2)


# =================================================================
# Download: ownership rules, inline preview, missing files
# =================================================================

class KYCDownloadTests(BaseTestCase):

    def make_doc(self, profile=None, **extra):
        return make_document(profile or self.partner_profile, **extra)

    def test_owner_can_download(self):
        document = self.make_doc()
        self.login_as(self.partner_user)
        response = self.client.get(reverse('kyc_document_download', args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.get('Content-Disposition', ''))

    def test_other_partner_is_denied(self):
        document = self.make_doc()
        self.login_as(self.partner_user2)
        response = self.client.get(reverse('kyc_document_download', args=[document.pk]))
        self.assertRedirects(response, reverse('kyc_document_list'))
        self.assertFalse(response.has_header('Content-Disposition'))

    def test_unapproved_partner_is_blocked(self):
        document = self.make_doc()
        self.login_as(self.unapproved_user)
        response = self.client.get(reverse('kyc_document_download', args=[document.pk]))
        self.assertRedirects(response, reverse('approval_pending'))

    def test_anonymous_is_redirected_to_login(self):
        document = self.make_doc()
        response = self.client.get(reverse('kyc_document_download', args=[document.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    def test_staff_can_download_any_document(self):
        document = self.make_doc()
        self.login_as(self.staff)
        response = self.client.get(reverse('kyc_document_download', args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.get('Content-Disposition', ''))

    def test_inline_flag_serves_without_attachment_header(self):
        document = self.make_doc()
        self.login_as(self.staff)
        response = self.client.get(
            reverse('kyc_document_download', args=[document.pk]), {'inline': '1'}
        )
        self.assertEqual(response.status_code, 200)
        disposition = response.get('Content-Disposition', '')
        self.assertNotIn('attachment', disposition)

    def test_document_without_file_redirects_with_error(self):
        document = PartnerDocument.objects.create(
            partner=self.partner_profile, doc_type='PAN'
        )
        self.login_as(self.partner_user)
        response = self.client.get(
            reverse('kyc_document_download', args=[document.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        rendered = [str(message) for message in response.context['messages']]
        self.assertTrue(any('File missing' in message for message in rendered))

    def test_missing_stored_bytes_redirect_with_error(self):
        document = PartnerDocument.objects.create(
            partner=self.partner_profile, doc_type='PAN', file='kyc/ghost.png'
        )
        self.login_as(self.partner_user)
        response = self.client.get(
            reverse('kyc_document_download', args=[document.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        rendered = [str(message) for message in response.context['messages']]
        self.assertTrue(any('File missing' in message for message in rendered))


# =================================================================
# Retry OCR: POST-only, ownership, processing guard
# =================================================================

class KYCRetryTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.document = make_document(self.partner_profile, 'PAN')
        self.document.ocr_status = 'failed'
        self.document.ocr_error = 'boom'
        self.document.save(update_fields=['ocr_status', 'ocr_error'])
        self.url = reverse('kyc_document_retry_ocr', args=[self.document.pk])

    def test_get_is_not_allowed(self):
        self.login_as(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.document.refresh_from_db()
        self.assertEqual(self.document.ocr_status, 'failed')

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    @mock.patch('partners.views.threading.Thread')
    def test_owner_can_retry(self, thread_cls):
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url)
        self.assertRedirects(response, reverse('kyc_document_list'))
        self.document.refresh_from_db()
        self.assertEqual(self.document.ocr_status, 'pending')
        self.assertEqual(self.document.ocr_error, '')
        thread_cls.assert_called_once()

    @mock.patch('partners.views.threading.Thread')
    def test_other_partner_cannot_retry(self, thread_cls):
        self.login_as(self.partner_user2)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url)
        self.assertRedirects(response, reverse('kyc_document_list'))
        self.document.refresh_from_db()
        self.assertEqual(self.document.ocr_status, 'failed')
        thread_cls.assert_not_called()

    @mock.patch('partners.views.threading.Thread')
    def test_staff_can_retry_from_detail_page(self, thread_cls):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url)
        self.assertRedirects(
            response, reverse('kyc_document_detail', args=[self.document.pk])
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.ocr_status, 'pending')
        thread_cls.assert_called_once()

    @mock.patch('partners.views.threading.Thread')
    def test_processing_document_cannot_be_retried(self, thread_cls):
        self.document.ocr_status = 'processing'
        self.document.save(update_fields=['ocr_status'])
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url)
        self.document.refresh_from_db()
        self.assertEqual(self.document.ocr_status, 'processing')
        thread_cls.assert_not_called()


# =================================================================
# Staff detail + review decision (POST-only) + notification
# =================================================================

class KYCDetailAndReviewTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.document = make_document(self.partner_profile, 'PAN')
        self.document.ocr_status = 'done'
        self.document.ocr_text = 'PAN ABCDE1234F\nXXXX XXXX 2105'
        self.document.extracted = {'pan': 'ABCDE1234F'}
        self.document.save(update_fields=['ocr_status', 'ocr_text', 'extracted'])
        self.detail_url = reverse('kyc_document_detail', args=[self.document.pk])
        self.review_url = reverse('kyc_document_review', args=[self.document.pk])

    def test_partner_cannot_open_detail_page(self):
        self.login_as(self.partner_user)
        response = self.client.get(self.detail_url)
        self.assertRedirects(response, reverse('dashboard'))

    def test_staff_detail_page_shows_text_suggestions_and_actions(self):
        self.login_as(self.staff)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'partners/kyc_review_detail.html')
        self.assertContains(response, 'ABCDE1234F')
        self.assertContains(response, 'XXXX XXXX 2105')
        self.assertContains(response, 'Suggested details')
        self.assertContains(response, 'Retry OCR')

    def test_review_get_is_not_allowed(self):
        self.login_as(self.staff)
        response = self.client.get(self.review_url)
        self.assertEqual(response.status_code, 405)
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, 'pending')

    def test_partner_cannot_review(self):
        self.login_as(self.partner_user)
        response = self.client.post(self.review_url, {'action': 'approve'})
        self.assertRedirects(response, reverse('dashboard'))
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, 'pending')

    @mock.patch('partners.views.notify')
    def test_staff_approve_records_decision_and_notifies(self, notify_mock):
        self.login_as(self.staff)
        response = self.client.post(
            self.review_url, {'action': 'approve', 'note': 'Looks good'}
        )
        self.assertRedirects(response, self.detail_url)
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, 'approved')
        self.assertEqual(self.document.reviewed_by, self.staff)
        self.assertIsNotNone(self.document.reviewed_at)
        self.assertEqual(self.document.review_note, 'Looks good')

        notify_mock.assert_called_once()
        args, _ = notify_mock.call_args
        self.assertEqual(args[0], self.partner_user)
        self.assertEqual(args[1], 'kyc_reviewed')
        self.assertEqual(args[2]['document'].pk, self.document.pk)
        self.assertEqual(args[2]['actor'], self.staff)

    @mock.patch('partners.views.notify')
    def test_staff_reject_records_note(self, notify_mock):
        self.login_as(self.staff)
        self.client.post(self.review_url, {'action': 'reject', 'note': 'Blurry scan'})
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, 'rejected')
        self.assertEqual(self.document.review_note, 'Blurry scan')
        notify_mock.assert_called_once()

    @mock.patch('partners.views.notify')
    def test_unknown_action_changes_nothing(self, notify_mock):
        self.login_as(self.staff)
        response = self.client.post(self.review_url, {'action': 'spam'})
        self.assertRedirects(response, self.detail_url)
        self.document.refresh_from_db()
        self.assertEqual(self.document.review_status, 'pending')
        notify_mock.assert_not_called()

    @override_settings(WHATSAPP_ENABLED=False)
    def test_review_decision_sends_a_real_notification(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.review_url, {'action': 'approve'})

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('KYC', mail.outbox[0].subject)
        log = NotificationLog.objects.filter(
            event='kyc_reviewed', channel='email'
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'sent')
        self.assertTrue(
            NotificationLog.objects.filter(
                event='kyc_reviewed', channel='whatsapp'
            ).exists()
        )


# =================================================================
# kyc_reviewed notification templates
# =================================================================

class KYCReviewedTemplateTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.document = make_document(self.partner_profile, 'PAN')
        self.document.review_status = 'approved'
        self.document.review_note = 'Verified'
        self.document.save(update_fields=['review_status', 'review_note'])
        self.context = build_context(
            'kyc_reviewed', EVENTS['kyc_reviewed'], self.partner_user,
            {'document': self.document},
        )

    def test_wa_template_is_short_plain_and_links_back(self):
        body = render_to_string(
            'notifications/kyc_reviewed.wa.txt', self.context
        ).strip()
        self.assertTrue(body.startswith('Partner Portal:'))
        self.assertLess(len(body), 400)
        self.assertIn('http', body)
        self.assertNotIn('<', body)

    def test_text_template_mentions_decision_and_link(self):
        body = render_to_string('notifications/kyc_reviewed.txt', self.context)
        self.assertIn(f'/partners/kyc/{self.document.pk}/', body)
        self.assertIn('Acme Corp', body)
        self.assertIn('Verified', body)

    def test_html_template_renders(self):
        body = render_to_string('notifications/kyc_reviewed.html', self.context)
        self.assertIn(f'/partners/kyc/{self.document.pk}/', body)
        self.assertIn('approved', body)
