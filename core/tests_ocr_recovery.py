"""Recovery of OCR runs interrupted by a server restart.

OCR runs on a daemon thread that dies when Render restarts the service, which
used to leave documents stuck in pending/processing. KYC pages now restart
such runs once (core.services.ocr.recover_stale_documents).
"""

from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.services.ocr import (
    AUTO_RETRY_NOTE, INTERRUPTED_ERROR, is_stale, process_document, recover_stale_documents,
)
from core.tests import BaseTestCase
from core.tests_phase3 import make_document
from partners.models import PartnerDocument

THREAD = 'partners.views.threading.Thread'


@override_settings(OCR_STALE_MINUTES=15)
class OCRRecoveryTests(BaseTestCase):

    def stuck(self, status='processing', minutes=20, error='', **extra):
        document = make_document(self.partner_profile, **extra)
        PartnerDocument.objects.filter(pk=document.pk).update(
            ocr_status=status, ocr_error=error,
            ocr_started_at=timezone.now() - timedelta(minutes=minutes),
        )
        document.refresh_from_db()
        return document

    def recover(self, documents=None):
        scheduled = []
        recover_stale_documents(documents or PartnerDocument.objects.all(), scheduled.append)
        return scheduled

    # --- is_stale -------------------------------------------------------

    def test_is_stale(self):
        self.assertTrue(is_stale(self.stuck(minutes=20)))
        self.assertTrue(is_stale(self.stuck(status='pending', minutes=20)))
        self.assertFalse(is_stale(self.stuck(minutes=5)))
        self.assertFalse(is_stale(self.stuck(status='done', minutes=60)))
        self.assertFalse(is_stale(self.stuck(status='failed', minutes=60)))

    def test_is_stale_falls_back_to_upload_time(self):
        document = self.stuck(minutes=20)
        PartnerDocument.objects.filter(pk=document.pk).update(
            ocr_started_at=None, uploaded_at=timezone.now() - timedelta(minutes=30),
        )
        document.refresh_from_db()
        self.assertTrue(is_stale(document))

    # --- recover_stale_documents ---------------------------------------

    def test_stuck_document_is_restarted_once(self):
        document = self.stuck()
        self.assertEqual(self.recover(), [document.pk])
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'pending')
        self.assertEqual(document.ocr_error, AUTO_RETRY_NOTE)
        self.assertGreater(document.ocr_started_at, timezone.now() - timedelta(minutes=1))

    def test_fresh_and_finished_documents_are_left_alone(self):
        running = self.stuck(minutes=5)
        done = self.stuck(status='done', minutes=60)
        failed = self.stuck(status='failed', minutes=60, error='bad file')
        self.assertEqual(self.recover(), [])
        for document, status in ((running, 'processing'), (done, 'done'), (failed, 'failed')):
            document.refresh_from_db()
            self.assertEqual(document.ocr_status, status)

    def test_second_interruption_marks_failed(self):
        document = self.stuck(error=AUTO_RETRY_NOTE)
        self.assertEqual(self.recover(), [])
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'failed')
        self.assertEqual(document.ocr_error, INTERRUPTED_ERROR)

    def test_document_is_claimed_only_once(self):
        document = self.stuck()
        self.assertEqual(self.recover(), [document.pk])
        # A second page load straight after must not restart it again.
        self.assertEqual(self.recover(), [])

    def test_only_given_documents_are_recovered(self):
        mine = self.stuck()
        other = self.stuck()
        PartnerDocument.objects.filter(pk=other.pk).update(partner=self.partner_profile2)
        scheduled = self.recover(PartnerDocument.objects.filter(partner=self.partner_profile))
        self.assertEqual(scheduled, [mine.pk])

    def test_never_raises(self):
        broken = mock.Mock()
        broken.filter.side_effect = RuntimeError('db down')
        with self.assertLogs('core.ocr', level='ERROR'):
            recover_stale_documents(broken, lambda pk: None)  # no exception

    @override_settings(OCR_ENABLED=False)
    def test_processing_records_start_time(self):
        document = make_document(self.partner_profile)
        with mock.patch('core.services.ocr.get_provider') as get_provider:
            provider = get_provider.return_value
            provider.name = 'tesseract'
            provider.extract_text.return_value = mock.Mock(ok=False, text='', error='x')
            process_document(document.pk)
        document.refresh_from_db()
        self.assertIsNotNone(document.ocr_started_at)

    # --- pages ----------------------------------------------------------

    @mock.patch(THREAD)
    def test_staff_kyc_list_restarts_stuck_documents(self, thread_cls):
        document = self.stuck()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(reverse('kyc_document_list'))
        self.assertEqual(response.status_code, 200)
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs['args'], (document.pk,))

    @mock.patch(THREAD)
    def test_detail_page_restarts_and_shows_note(self, thread_cls):
        document = self.stuck()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(reverse('kyc_document_detail', args=[document.pk]))
        self.assertContains(response, AUTO_RETRY_NOTE)
        thread_cls.assert_called_once()

    @mock.patch(THREAD)
    def test_partner_kyc_list_restarts_only_own_documents(self, thread_cls):
        mine = self.stuck()
        other = self.stuck()
        PartnerDocument.objects.filter(pk=other.pk).update(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse('kyc_document_list'))
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs['args'], (mine.pk,))
        other.refresh_from_db()
        self.assertEqual(other.ocr_status, 'processing')

    # --- retry button ---------------------------------------------------

    @mock.patch(THREAD)
    def test_stuck_processing_document_can_be_retried(self, thread_cls):
        document = self.stuck()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('kyc_document_retry_ocr', args=[document.pk]))
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'pending')
        self.assertEqual(document.ocr_error, '')
        thread_cls.assert_called_once()

    @mock.patch(THREAD)
    def test_running_document_still_cannot_be_retried(self, thread_cls):
        document = self.stuck(minutes=2)
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('kyc_document_retry_ocr', args=[document.pk]))
        document.refresh_from_db()
        self.assertEqual(document.ocr_status, 'processing')
        thread_cls.assert_not_called()

    @mock.patch(THREAD)
    def test_upload_and_retry_record_start_time(self, thread_cls):
        document = self.stuck(status='failed', minutes=60, error='x')
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('kyc_document_retry_ocr', args=[document.pk]))
        document.refresh_from_db()
        self.assertGreater(document.ocr_started_at, timezone.now() - timedelta(minutes=1))
