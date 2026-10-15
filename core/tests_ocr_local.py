"""Local OCR (Tesseract) and hybrid provider tests.

The tesseract / pdftoppm binaries are never executed: ``shutil.which`` and
``subprocess.run`` are mocked, and every OCR.space call is mocked too, so
these tests run offline on any machine.
"""

import os
import subprocess
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core.services import ocr
from core.services.ocr import (
    HybridProvider,
    OCRSpaceProvider,
    TesseractProvider,
    get_provider,
    process_document,
    quota_available,
)
from core.tests import BaseTestCase
from core.tests_phase3 import KEY, FakeOCRResponse, make_document, ocr_payload

WHICH = 'core.services.ocr.shutil.which'
RUN = 'core.services.ocr.subprocess.run'
LONG_TEXT = 'INCOME TAX DEPARTMENT Permanent Account Number ABCDE1234F'

LOCAL_ON = {
    'OCR_ENABLED': True,
    'OCR_PROVIDER': 'tesseract',
    'OCRSPACE_API_KEY': KEY,
    'OCR_DAILY_LIMIT': 1,
    'OCR_MAX_BYTES': 16,
    'OCR_TESSERACT_LANG': 'eng+hin',
    'OCR_TESSERACT_TIMEOUT': 30,
    'OCR_PDF_MAX_PAGES': 3,
}


def found(name):
    return f'/usr/bin/{name}'


def completed(stdout=b'', returncode=0, stderr=b''):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def fake_run(page_count=2, text=b'page text'):
    """subprocess.run stand-in: pdftoppm writes PNG pages, tesseract prints text."""
    calls = []

    def _run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == 'pdftoppm':
            prefix = command[-1]
            for index in range(1, page_count + 1):
                with open(f'{prefix}-{index}.png', 'wb') as handle:
                    handle.write(b'png')
            return completed()
        return completed(stdout=text + b' ' + os.path.basename(command[1]).encode())
    return _run, calls


class TesseractProviderTests(SimpleTestCase):

    def provider(self, **kwargs):
        return TesseractProvider(lang='eng+hin', timeout=30, max_pages=3, **kwargs)

    @mock.patch(RUN)
    @mock.patch(WHICH, return_value=None)
    def test_missing_binary_fails_without_running(self, which, run):
        result = self.provider().extract_text(b'png', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertEqual(result.provider, 'tesseract')
        self.assertIn('not installed', result.error)
        run.assert_not_called()

    @mock.patch(WHICH, side_effect=found)
    def test_image_runs_tesseract_with_languages_and_timeout(self, which):
        with mock.patch(RUN, return_value=completed(stdout=LONG_TEXT.encode())) as run:
            result = self.provider().extract_text(b'\x89PNG data', 'scan.png', 'image/png')

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.text, LONG_TEXT)
        self.assertEqual(result.provider, 'tesseract')
        command = run.call_args.args[0]
        self.assertEqual(command[0], 'tesseract')
        self.assertTrue(command[1].endswith('input.png'))
        self.assertEqual(command[2:], ['stdout', '-l', 'eng+hin'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        self.assertEqual(run.call_args.kwargs['env']['OMP_THREAD_LIMIT'], '1')

    @mock.patch(WHICH, side_effect=found)
    def test_temporary_files_are_removed(self, which):
        seen = []

        def _run(command, **kwargs):
            seen.append(command[1])
            self.assertTrue(os.path.exists(command[1]))
            return completed(stdout=b'text')

        with mock.patch(RUN, side_effect=_run):
            self.provider().extract_text(b'img', 'scan.jpg', 'image/jpeg')
        self.assertFalse(os.path.exists(seen[0]))

    @mock.patch(WHICH, side_effect=found)
    def test_pdf_pages_are_rendered_then_read_in_order(self, which):
        run_side_effect, calls = fake_run(page_count=2)
        with mock.patch(RUN, side_effect=run_side_effect):
            result = self.provider().extract_text(b'%PDF-1.4 data', 'doc.pdf', 'application/pdf')

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.text, 'page text page-1.png\npage text page-2.png')
        pdftoppm = calls[0][0]
        self.assertEqual(pdftoppm[0], 'pdftoppm')
        self.assertEqual(pdftoppm[pdftoppm.index('-l') + 1], '3')
        self.assertEqual([c[0][0] for c in calls], ['pdftoppm', 'tesseract', 'tesseract'])

    @mock.patch(WHICH, side_effect=found)
    def test_pdf_detected_by_magic_bytes(self, which):
        run_side_effect, calls = fake_run(page_count=1)
        with mock.patch(RUN, side_effect=run_side_effect):
            self.provider().extract_text(b'%PDF-1.7 data', 'upload', '')
        self.assertEqual(calls[0][0][0], 'pdftoppm')

    @mock.patch(RUN)
    @mock.patch(WHICH, side_effect=lambda name: None if name == 'pdftoppm' else found(name))
    def test_pdf_without_poppler_fails_cleanly(self, which, run):
        result = self.provider().extract_text(b'%PDF-1.4', 'doc.pdf', 'application/pdf')
        self.assertFalse(result.ok)
        self.assertIn('pdftoppm', result.error)
        run.assert_not_called()

    @mock.patch(WHICH, side_effect=found)
    def test_pdf_with_no_pages_fails(self, which):
        with mock.patch(RUN, return_value=completed()):
            result = self.provider().extract_text(b'%PDF-1.4', 'doc.pdf', 'application/pdf')
        self.assertFalse(result.ok)
        self.assertIn('no readable pages', result.error)

    @mock.patch(WHICH, side_effect=found)
    def test_nonzero_exit_is_a_failed_result(self, which):
        failing = completed(returncode=1, stderr=b'Error opening data file hin.traineddata')
        with mock.patch(RUN, return_value=failing):
            result = self.provider().extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('hin.traineddata', result.error)

    @mock.patch(WHICH, side_effect=found)
    def test_timeout_is_a_failed_result(self, which):
        with mock.patch(RUN, side_effect=subprocess.TimeoutExpired(cmd='tesseract', timeout=30)):
            result = self.provider().extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('timed out after 30s', result.error)

    @mock.patch(WHICH, side_effect=found)
    def test_unexpected_exception_never_raises_and_releases_lock(self, which):
        with mock.patch(RUN, side_effect=RuntimeError('boom')):
            result = self.provider().extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('boom', result.error)
        self.assertFalse(ocr._local_ocr_lock.locked())

    @mock.patch(WHICH, side_effect=found)
    def test_huge_image_is_shrunk_before_tesseract(self, which):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is not installed')
        import io
        buffer = io.BytesIO()
        Image.new('RGB', (ocr.LOCAL_MAX_SIDE + 500, 100), color='white').save(buffer, format='JPEG')
        sizes = []

        def _run(command, **kwargs):
            sizes.append(Image.open(command[1]).size)
            return completed(stdout=b'text')

        with mock.patch(RUN, side_effect=_run):
            self.provider().extract_text(buffer.getvalue(), 'photo.jpg', 'image/jpeg')
        self.assertEqual(max(sizes[0]), ocr.LOCAL_MAX_SIDE)

    @mock.patch(WHICH, side_effect=found)
    def test_text_is_capped(self, which):
        with mock.patch(RUN, return_value=completed(stdout=b'x' * (ocr.MAX_TEXT + 100))):
            result = self.provider().extract_text(b'img', 'scan.png', 'image/png')
        self.assertEqual(len(result.text), ocr.MAX_TEXT)


@override_settings(OCR_DAILY_LIMIT=5, OCR_MAX_BYTES=1024 * 1024)
class HybridProviderTests(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.local = mock.Mock(spec=TesseractProvider)
        self.remote = OCRSpaceProvider(KEY)
        self.hybrid = HybridProvider(self.local, self.remote)

    def local_returns(self, ok=True, text='', error=''):
        self.local.extract_text.return_value = ocr.OCRResult(ok, text, error, 'tesseract')

    def test_good_local_text_skips_ocrspace(self):
        self.local_returns(text=LONG_TEXT)
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertEqual(result.provider, 'tesseract')
        urlopen.assert_not_called()
        self.assertEqual(cache.get(ocr._quota_key()), None)

    def test_short_local_text_falls_back_and_uses_quota(self):
        self.local_returns(text='abc')
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload(LONG_TEXT))):
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, 'ocrspace')
        self.assertEqual(result.text, LONG_TEXT)
        self.assertEqual(cache.get(ocr._quota_key()), 1)

    def test_local_failure_falls_back(self):
        self.local_returns(ok=False, error='Tesseract is not installed on this server')
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload(LONG_TEXT))):
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, 'ocrspace')

    def test_keeps_local_text_when_fallback_finds_less(self):
        self.local_returns(text='short text')
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload(''))):
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertTrue(result.ok)
        self.assertEqual(result.text, 'short text')

    def test_both_failing_reports_both_errors(self):
        self.local_returns(ok=False, error='tesseract timed out after 120s')
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload('', error='quota'))):
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertFalse(result.ok)
        self.assertIn('timed out', result.error)
        self.assertIn('quota', result.error)

    @override_settings(OCR_DAILY_LIMIT=1)
    def test_no_fallback_when_quota_is_used_up(self):
        ocr.bump_quota()
        self.local_returns(text='abc')
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            result = self.hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertEqual(result.text, 'abc')
        urlopen.assert_not_called()

    def test_no_fallback_without_api_key(self):
        hybrid = HybridProvider(self.local, OCRSpaceProvider(''))
        self.local_returns(text='abc')
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            result = hybrid.extract_text(b'img', 'scan.png', 'image/png')
        self.assertEqual(result.text, 'abc')
        urlopen.assert_not_called()

    @override_settings(OCR_MAX_BYTES=16)
    def test_no_fallback_when_file_too_big_for_ocrspace(self):
        self.local_returns(text='abc')
        with mock.patch('core.services.ocr.urlopen') as urlopen:
            result = self.hybrid.extract_text(b'%PDF-1.4' + b'x' * 100, 'doc.pdf', 'application/pdf')
        self.assertEqual(result.text, 'abc')
        urlopen.assert_not_called()


class LocalProviderSettingsTests(SimpleTestCase):

    @override_settings(**LOCAL_ON)
    def test_tesseract_provider_uses_settings(self):
        provider = get_provider()
        self.assertIsInstance(provider, TesseractProvider)
        self.assertEqual(provider.lang, 'eng+hin')
        self.assertEqual(provider.timeout, 30)
        self.assertEqual(provider.max_pages, 3)

    @override_settings(**dict(LOCAL_ON, OCR_PROVIDER='Hybrid'))
    def test_hybrid_provider(self):
        provider = get_provider()
        self.assertIsInstance(provider, HybridProvider)
        self.assertIsInstance(provider.local, TesseractProvider)
        self.assertEqual(provider.remote.api_key, KEY)

    @override_settings(OCR_ENABLED=True, OCR_PROVIDER='ocrspace', OCRSPACE_API_KEY=KEY)
    def test_default_provider_unchanged(self):
        self.assertIsInstance(get_provider(), OCRSpaceProvider)

    @override_settings(**dict(LOCAL_ON, OCR_ENABLED=False))
    def test_disabled_still_returns_none(self):
        self.assertIsNone(get_provider())


@override_settings(**LOCAL_ON)
class LocalOCRWorkerTests(BaseTestCase):
    """process_document with Tesseract: no quota, no size cap, masking still applies."""

    def setUp(self):
        super().setUp()
        cache.clear()

    @mock.patch('core.services.ocr.urlopen')
    @mock.patch(WHICH, side_effect=found)
    def test_success_masks_aadhaar_and_ignores_quota_and_size(self, which, urlopen):
        ocr.bump_quota()  # OCR.space quota (limit 1) is now used up
        self.assertFalse(quota_available())
        text = b'Aadhaar 1234 5678 9012 PAN ABCDE1234F'
        document = make_document(self.partner_profile, content=b'\x89PNG' + b'x' * 500)

        with mock.patch(RUN, return_value=completed(stdout=text)):
            process_document(document.pk)
        document.refresh_from_db()

        self.assertEqual(document.ocr_status, 'done')
        self.assertNotIn('1234 5678 9012', document.ocr_text)
        self.assertIn('9012', document.ocr_text)
        self.assertEqual(document.extracted.get('pan'), 'ABCDE1234F')
        self.assertEqual(cache.get(ocr._quota_key()), 1)  # not bumped
        urlopen.assert_not_called()

    @mock.patch(WHICH, return_value=None)
    def test_missing_tesseract_marks_failed(self, which):
        document = make_document(self.partner_profile)
        process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertIn('not installed', document.ocr_error)

    @override_settings(OCR_PROVIDER='hybrid', OCR_MAX_BYTES=1024 * 1024, OCR_DAILY_LIMIT=10)
    @mock.patch(WHICH, return_value=None)
    def test_hybrid_without_tesseract_still_works_through_ocrspace(self, which):
        document = make_document(self.partner_profile)
        with mock.patch('core.services.ocr.urlopen', return_value=FakeOCRResponse(ocr_payload(LONG_TEXT))):
            process_document(document.pk)
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'done')
        self.assertIn('ABCDE1234F', document.ocr_text)
        self.assertEqual(cache.get(ocr._quota_key()), 1)
