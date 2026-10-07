"""
Phase 0 Security Test Suite
============================
Covers all requirements from Phase 0:
  S1  Orders: partner access control, commission validation
  S2  POST-only enforcement on state-changing views
  S3  Privilege escalation through UserForm
  S4  Partner approval workflow
  S5  Document download authentication & missing file handling
  S7  Robustness: no 500 for users without a PartnerProfile

Run with:
    python manage.py test core.tests --verbosity=2
"""

import io
import json
import re
import tempfile
import urllib.error
from unittest import mock

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError

from partners.models import PartnerProfile
from leads.models import Lead
from orders.models import Order
from support.models import Ticket
from portal_content.models import Document, Announcement


# -----------------------------------------------------------------
# Base TestCase with shared fixtures
# -----------------------------------------------------------------

class BaseTestCase(TestCase):
    """Creates a standard set of users and profiles used by most tests."""

    def setUp(self):
        # Superuser
        self.superuser = User.objects.create_superuser(
            username='super', password='pass1234', email='super@test.com'
        )
        # Non-superuser staff
        self.staff = User.objects.create_user(
            username='staff', password='pass1234', email='staff@test.com',
            is_staff=True
        )
        # Approved partner 1
        self.partner_user = User.objects.create_user(
            username='partner1', password='pass1234', email='p1@test.com'
        )
        self.partner_profile = PartnerProfile.objects.create(
            user=self.partner_user,
            company_name='Acme Corp',
            phone_number='9876543210',
            is_approved=True
        )
        # Approved partner 2 (for cross-partner isolation)
        self.partner_user2 = User.objects.create_user(
            username='partner2', password='pass1234', email='p2@test.com'
        )
        self.partner_profile2 = PartnerProfile.objects.create(
            user=self.partner_user2,
            company_name='Beta Ltd',
            phone_number='9876543211',
            is_approved=True
        )
        # Unapproved partner
        self.unapproved_user = User.objects.create_user(
            username='unapproved', password='pass1234', email='un@test.com'
        )
        self.unapproved_profile = PartnerProfile.objects.create(
            user=self.unapproved_user,
            company_name='Pending Co',
            phone_number='9000000001',
            is_approved=False
        )
        # User with NO PartnerProfile
        self.no_profile_user = User.objects.create_user(
            username='noprofile', password='pass1234', email='np@test.com'
        )
        self.client = Client()

    def login_as(self, user, password='pass1234'):
        self.client.login(username=user.username, password=password)

    def make_lead(self, partner=None):
        partner = partner or self.partner_profile
        return Lead.objects.create(
            partner=partner,
            customer_name='Test Customer',
            customer_phone='9123456789',
            product_interest='Software',
        )

    def make_order(self, partner=None, amount='1000.00', commission='100.00'):
        partner = partner or self.partner_profile
        lead = self.make_lead(partner)
        return Order.objects.create(
            partner=partner,
            lead=lead,
            order_number='ORD{:04d}'.format(Order.objects.count() + 1),
            amount=amount,
            commission_amount=commission,
        )

    def make_ticket(self, partner=None):
        partner = partner or self.partner_profile
        return Ticket.objects.create(
            partner=partner,
            subject='Test Ticket',
            description='Help me!',
        )


# =================================================================
# S1  ORDERS: PARTNER ACCESS CONTROL
# =================================================================

class OrderPartnerAccessTests(BaseTestCase):

    def test_partner_cannot_update_order(self):
        """Partner is redirected away from order_update and the order is unchanged."""
        order = self.make_order()
        self.login_as(self.partner_user)
        resp = self.client.post(reverse('order_update', args=[order.pk]), {
            'partner': self.partner_profile.pk,
            'lead': order.lead.pk,
            'order_number': order.order_number,
            'amount': '2000.00',
            'commission_amount': '500.00',
            'status': 'COMPLETED',
            'is_commission_paid': True,
        })
        self.assertIn(resp.status_code, [302, 403])
        order.refresh_from_db()
        self.assertEqual(str(order.amount), '1000.00')

    def test_partner_cannot_delete_order_post(self):
        """Partner POST to order_delete is rejected and order survives."""
        order = self.make_order()
        self.login_as(self.partner_user)
        resp = self.client.post(reverse('order_delete', args=[order.pk]))
        self.assertIn(resp.status_code, [302, 403])
        order.refresh_from_db()
        self.assertFalse(order.is_deleted)

    def test_admin_can_update_order(self):
        """Staff can edit an order successfully."""
        order = self.make_order()
        self.login_as(self.staff)
        resp = self.client.post(reverse('order_update', args=[order.pk]), {
            'partner': self.partner_profile.pk,
            'lead': order.lead.pk,
            'order_number': order.order_number,
            'amount': '1500.00',
            'commission_amount': '150.00',
            'status': 'COMPLETED',
            'is_commission_paid': False,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(str(order.amount), '1500.00')

    def test_admin_can_delete_order(self):
        """Staff can soft-delete an order via POST."""
        order = self.make_order()
        self.login_as(self.staff)
        self.client.post(reverse('order_delete', args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.is_deleted)

    def test_commission_cannot_exceed_amount(self):
        """OrderForm: commission_amount > amount is invalid."""
        from orders.forms import OrderForm
        lead = self.make_lead()
        form = OrderForm(data={
            'partner': self.partner_profile.pk,
            'lead': lead.pk,
            'order_number': 'BADORD001',
            'amount': '500.00',
            'commission_amount': '600.00',
            'status': 'PENDING',
            'is_commission_paid': False,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('commission_amount', form.errors)

    def test_commission_cannot_be_negative(self):
        """OrderForm: negative commission_amount is invalid."""
        from orders.forms import OrderForm
        lead = self.make_lead()
        form = OrderForm(data={
            'partner': self.partner_profile.pk,
            'lead': lead.pk,
            'order_number': 'BADORD002',
            'amount': '500.00',
            'commission_amount': '-10.00',
            'status': 'PENDING',
            'is_commission_paid': False,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('commission_amount', form.errors)

    def test_partner_cannot_see_other_partner_order(self):
        """Partner1 cannot see Partner2's orders in the order list."""
        order2 = self.make_order(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('order_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, order2.order_number)


# =================================================================
# S2  POST-ONLY ENFORCEMENT
# =================================================================

class PostOnlyTests(BaseTestCase):
    """GET on every state-changing view must return 405."""

    def _assert_405_on_get(self, url_name, *args):
        self.login_as(self.staff)
        resp = self.client.get(reverse(url_name, args=args))
        self.assertEqual(
            resp.status_code, 405,
            msg='Expected 405 on GET {}, got {}'.format(url_name, resp.status_code)
        )

    def test_lead_delete_get_405(self):
        self._assert_405_on_get('lead_delete', self.make_lead().pk)

    def test_lead_update_status_get_405(self):
        self._assert_405_on_get('lead_update_status', self.make_lead().pk)

    def test_order_delete_get_405(self):
        self._assert_405_on_get('order_delete', self.make_order().pk)

    def test_order_update_status_get_405(self):
        self._assert_405_on_get('order_update_status', self.make_order().pk)

    def test_order_mark_commission_paid_get_405(self):
        self._assert_405_on_get('order_mark_commission_paid', self.make_order().pk)

    def test_order_mark_commission_unpaid_get_405(self):
        self._assert_405_on_get('order_mark_commission_unpaid', self.make_order().pk)

    def test_ticket_delete_get_405(self):
        self._assert_405_on_get('ticket_delete', self.make_ticket().pk)

    def test_ticket_update_status_get_405(self):
        self._assert_405_on_get('ticket_update_status', self.make_ticket().pk)

    def test_partner_delete_get_405(self):
        self._assert_405_on_get('partner_delete', self.partner_profile.pk)

    def test_partner_approve_get_405(self):
        self._assert_405_on_get('partner_approve', self.partner_profile.pk)

    def test_user_delete_get_405(self):
        u = User.objects.create_user(username='throwaway', password='pass1234')
        self._assert_405_on_get('user_delete', u.pk)

    def test_group_delete_get_405(self):
        from django.contrib.auth.models import Group
        g = Group.objects.create(name='TestGroup')
        self._assert_405_on_get('group_delete', g.pk)

    def test_restore_item_get_405(self):
        lead = self.make_lead()
        lead.soft_delete(self.staff)
        self._assert_405_on_get('restore_item', 'lead', lead.pk)

    def test_hard_delete_item_get_405(self):
        lead = self.make_lead()
        lead.soft_delete(self.staff)
        self._assert_405_on_get('hard_delete_item', 'lead', lead.pk)

    def test_empty_bin_get_405(self):
        self._assert_405_on_get('empty_bin', 'lead')

    def test_notifications_mark_read_get_405(self):
        self._assert_405_on_get('notifications_mark_read')

    def test_announcement_delete_get_405(self):
        a = Announcement.objects.create(title='Test', content='Body')
        self._assert_405_on_get('announcement_delete', a.pk)

    def test_document_delete_get_405(self):
        doc = Document.objects.create(
            title='Doc',
            file=SimpleUploadedFile('test.pdf', b'%PDF', content_type='application/pdf')
        )
        self._assert_405_on_get('document_delete', doc.pk)


# =================================================================
# S3  PRIVILEGE ESCALATION
# =================================================================

class PrivilegeEscalationTests(BaseTestCase):

    def test_non_superuser_staff_cannot_grant_is_superuser(self):
        target = User.objects.create_user(
            username='target_user', password='pass1234', email='target@test.com'
        )
        self.login_as(self.staff)
        self.client.post(reverse('user_update', args=[target.pk]), {
            'username': target.username,
            'email': target.email,
            'password': '',
            'is_active': True,
            'is_staff': True,
            'is_superuser': True,
            'groups': [],
        })
        target.refresh_from_db()
        self.assertFalse(target.is_superuser)

    def test_non_superuser_staff_cannot_grant_is_staff(self):
        target = User.objects.create_user(
            username='target_staff', password='pass1234', email='ts@test.com'
        )
        self.login_as(self.staff)
        self.client.post(reverse('user_update', args=[target.pk]), {
            'username': target.username,
            'email': target.email,
            'password': '',
            'is_active': True,
            'is_staff': True,
            'groups': [],
        })
        target.refresh_from_db()
        self.assertFalse(target.is_staff)

    def test_staff_cannot_edit_superuser(self):
        self.login_as(self.staff)
        resp = self.client.get(reverse('user_update', args=[self.superuser.pk]))
        self.assertIn(resp.status_code, [302, 403])

    def test_staff_cannot_delete_superuser(self):
        self.login_as(self.staff)
        self.client.post(reverse('user_delete', args=[self.superuser.pk]))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

    def test_user_cannot_delete_themselves(self):
        self.login_as(self.staff)
        self.client.post(reverse('user_delete', args=[self.staff.pk]))
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_last_superuser_cannot_be_deleted(self):
        self.login_as(self.superuser)
        self.client.post(reverse('user_delete', args=[self.superuser.pk]))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

    def test_last_superuser_cannot_be_demoted(self):
        from partners.forms import UserForm
        form = UserForm(
            data={
                'username': self.superuser.username,
                'email': self.superuser.email,
                'password': '',
                'is_active': True,
                'is_staff': True,
                'is_superuser': False,
                'groups': [],
            },
            instance=self.superuser,
            current_user=self.superuser,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('is_superuser', form.errors)


# =================================================================
# S4  PARTNER APPROVAL WORKFLOW
# =================================================================

class PartnerApprovalTests(BaseTestCase):

    def test_new_registration_is_unapproved(self):
        self.client.post(reverse('register'), {
            'username': 'newpartner',
            'email': 'newp@test.com',
            'password': 'Secure@1234',
            'confirm_password': 'Secure@1234',
            'company_name': 'New Corp',
            'phone_number': '9000000099',
        })
        profile = PartnerProfile.objects.get(user__username='newpartner')
        self.assertFalse(profile.is_approved)

    def test_unapproved_partner_blocked_from_leads(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('lead_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('approval', resp['Location'])

    def test_unapproved_partner_blocked_from_orders(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('order_list'))
        self.assertEqual(resp.status_code, 302)

    def test_unapproved_partner_blocked_from_tickets(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('ticket_list'))
        self.assertEqual(resp.status_code, 302)

    def test_unapproved_partner_blocked_from_documents(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('document_list'))
        self.assertEqual(resp.status_code, 302)

    def test_approved_partner_can_access_leads(self):
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('lead_list'))
        self.assertEqual(resp.status_code, 200)

    def test_approval_toggle_by_staff(self):
        self.login_as(self.staff)
        url = reverse('partner_approve', args=[self.unapproved_profile.pk])
        self.client.post(url, {'is_approved': 'true'})
        self.unapproved_profile.refresh_from_db()
        self.assertTrue(self.unapproved_profile.is_approved)
        self.client.post(url, {'is_approved': 'false'})
        self.unapproved_profile.refresh_from_db()
        self.assertFalse(self.unapproved_profile.is_approved)

    def test_staff_unaffected_by_approval_check(self):
        self.login_as(self.staff)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)


# =================================================================
# S5  DOCUMENT DOWNLOAD AUTHENTICATION
# =================================================================

class DocumentDownloadTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.doc = Document.objects.create(
            title='Test Doc',
            file=SimpleUploadedFile(
                name='test_report.pdf',
                content=b'%PDF-1.4 fake pdf content',
                content_type='application/pdf'
            )
        )

    def tearDown(self):
        try:
            if self.doc.file:
                self.doc.file.delete(save=False)
        except Exception:
            pass

    def test_anonymous_cannot_download(self):
        self.client.logout()
        resp = self.client.get(reverse('document_download', args=[self.doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_unapproved_partner_cannot_download(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('document_download', args=[self.doc.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_approved_partner_can_download_public_doc(self):
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('document_download', args=[self.doc.pk]))
        self.assertNotEqual(resp.status_code, 500)
        self.assertNotEqual(resp.status_code, 403)

    def test_missing_file_no_500(self):
        missing = Document.objects.create(title='Missing File Doc')
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('document_download', args=[missing.pk]))
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 302)

    def test_restricted_doc_inaccessible_by_other_partner(self):
        restricted = Document.objects.create(
            title='Private Doc',
            file=SimpleUploadedFile('private.pdf', b'%PDF private', content_type='application/pdf')
        )
        restricted.visible_to.add(self.partner_profile)
        try:
            self.login_as(self.partner_user2)
            resp = self.client.get(reverse('document_download', args=[restricted.pk]))
            self.assertNotEqual(resp.status_code, 200)
        finally:
            try:
                restricted.file.delete(save=False)
            except Exception:
                pass


# =================================================================
# S7  ROBUSTNESS: NO 500 FOR USERS WITHOUT PARTNER PROFILE
# =================================================================

class NoProfileRobustnessTests(BaseTestCase):

    def test_no_profile_dashboard_no_500(self):
        self.login_as(self.no_profile_user)
        resp = self.client.get(reverse('dashboard'))
        self.assertNotEqual(resp.status_code, 500)

    def test_no_profile_lead_list_no_500(self):
        self.login_as(self.no_profile_user)
        resp = self.client.get(reverse('lead_list'))
        self.assertNotEqual(resp.status_code, 500)

    def test_no_profile_order_list_no_500(self):
        self.login_as(self.no_profile_user)
        resp = self.client.get(reverse('order_list'))
        self.assertNotEqual(resp.status_code, 500)

    def test_no_profile_ticket_list_no_500(self):
        self.login_as(self.no_profile_user)
        resp = self.client.get(reverse('ticket_list'))
        self.assertNotEqual(resp.status_code, 500)

    def test_no_profile_profile_page_no_500(self):
        self.login_as(self.no_profile_user)
        resp = self.client.get(reverse('profile'))
        self.assertNotEqual(resp.status_code, 500)

    def test_staff_without_profile_no_500(self):
        self.login_as(self.staff)
        for url_name in ['dashboard', 'lead_list', 'order_list', 'ticket_list']:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertNotEqual(resp.status_code, 500)


# =================================================================
# CROSS-PARTNER ISOLATION
# =================================================================

class CrossPartnerIsolationTests(BaseTestCase):

    def test_partner_cannot_see_other_lead(self):
        lead2 = self.make_lead(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('lead_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, lead2.customer_name)

    def test_partner_cannot_edit_other_lead(self):
        lead2 = self.make_lead(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        self.client.post(reverse('lead_update', args=[lead2.pk]), {
            'customer_name': 'Hacked',
            'customer_phone': '9000000000',
            'product_interest': 'Hacking',
        })
        lead2.refresh_from_db()
        self.assertNotEqual(lead2.customer_name, 'Hacked')

    def test_partner_cannot_delete_other_lead(self):
        lead2 = self.make_lead(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        self.client.post(reverse('lead_delete', args=[lead2.pk]))
        lead2.refresh_from_db()
        self.assertFalse(lead2.is_deleted)

    def test_partner_cannot_see_other_ticket(self):
        ticket2 = self.make_ticket(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('ticket_list'))
        self.assertNotContains(resp, ticket2.subject)

    def test_partner_cannot_edit_other_ticket(self):
        ticket2 = self.make_ticket(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        self.client.post(reverse('ticket_update', args=[ticket2.pk]), {
            'subject': 'Hijacked',
            'description': 'Pwned',
        })
        ticket2.refresh_from_db()
        self.assertNotEqual(ticket2.subject, 'Hijacked')

    def test_partner_cannot_see_other_order(self):
        order2 = self.make_order(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('order_list'))
        self.assertNotContains(resp, order2.order_number)


# =================================================================
# COMMISSION PAID TOGGLE
# =================================================================

class CommissionPaidTests(BaseTestCase):

    def test_admin_can_mark_paid(self):
        order = self.make_order()
        self.login_as(self.staff)
        self.client.post(reverse('order_mark_commission_paid', args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.is_commission_paid)

    def test_admin_can_mark_unpaid(self):
        order = self.make_order()
        order.is_commission_paid = True
        order.save()
        self.login_as(self.staff)
        self.client.post(reverse('order_mark_commission_unpaid', args=[order.pk]))
        order.refresh_from_db()
        self.assertFalse(order.is_commission_paid)

    def test_partner_cannot_mark_paid(self):
        order = self.make_order()
        self.login_as(self.partner_user)
        self.client.post(reverse('order_mark_commission_paid', args=[order.pk]))
        order.refresh_from_db()
        self.assertFalse(order.is_commission_paid)


# =================================================================
# GET_PARTNER_PROFILE UTILITY
# =================================================================

class GetPartnerProfileTests(TestCase):

    def test_returns_none_for_anonymous(self):
        from partners.utils import get_partner_profile
        from django.contrib.auth.models import AnonymousUser
        self.assertIsNone(get_partner_profile(AnonymousUser()))

    def test_returns_none_for_user_without_profile(self):
        from partners.utils import get_partner_profile
        user = User.objects.create_user(username='bare_user', password='pass')
        self.assertIsNone(get_partner_profile(user))

    def test_returns_profile_for_valid_user(self):
        from partners.utils import get_partner_profile
        user = User.objects.create_user(username='pp_user', password='pass')
        profile = PartnerProfile.objects.create(
            user=user, company_name='Test Co', phone_number='9000000002'
        )
        self.assertEqual(get_partner_profile(user), profile)


# =================================================================
# PHASE 1A  DOCUMENTS STORED IN THE DATABASE
# =================================================================

class DocumentDatabaseStorageTests(BaseTestCase):
    """Uploads are kept in core.models.StoredFile (DatabaseFileStorage)."""

    PDF_BYTES = b'%PDF-1.4 stored in the database'

    def _make_doc(self, name='stored_doc.pdf', visible_to=None):
        doc = Document.objects.create(
            title='Stored Doc',
            file=SimpleUploadedFile(name, self.PDF_BYTES, content_type='application/pdf'),
        )
        if visible_to:
            doc.visible_to.set(visible_to)
        return doc

    def test_upload_then_download_works_for_approved_partner(self):
        doc = self._make_doc()
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('document_download', args=[doc.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), self.PDF_BYTES)
        self.assertIn('application/pdf', resp['Content-Type'])
        self.assertIn('stored_doc.pdf', resp['Content-Disposition'])
        from core.models import StoredFile
        self.assertTrue(StoredFile.objects.filter(name=doc.file.name).exists())

    def test_anonymous_user_is_redirected_to_login(self):
        doc = self._make_doc()
        self.client.logout()
        resp = self.client.get(reverse('document_download', args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_partner_not_in_visible_to_cannot_download(self):
        doc = self._make_doc(visible_to=[self.partner_profile])
        self.login_as(self.partner_user2)
        resp = self.client.get(reverse('document_download', args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.status_code, 200)

    def test_soft_delete_keeps_bytes_and_permanent_delete_removes_them(self):
        from core.models import StoredFile
        doc = self._make_doc()
        name = doc.file.name
        self.assertTrue(StoredFile.objects.filter(name=name).exists())

        doc.soft_delete(self.staff)
        self.assertTrue(StoredFile.objects.filter(name=name).exists())

        doc.hard_delete()
        self.assertFalse(StoredFile.objects.filter(name=name).exists())

    def test_missing_stored_bytes_do_not_cause_500(self):
        doc = Document.objects.create(
            title='Lost Doc', file='documents/lost_doc.pdf'
        )
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('document_download', args=[doc.pk]))
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 302)

        list_resp = self.client.get(reverse('document_list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, 'File missing')


# =================================================================
# PHASE 1B  PASSWORD RESET BY EMAIL
# =================================================================

class PasswordResetTests(BaseTestCase):
    """Anonymous reset flow: pages, throttling, email delivery, pending partners."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_request_page_get_returns_200(self):
        resp = self.client.get(reverse('password_reset'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Forgot Password')
        self.assertContains(resp, 'name="email"')

    def test_login_page_has_forgot_password_link(self):
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Forgot password?')

    def test_known_email_sends_one_working_reset_link(self):
        resp = self.client.post(reverse('password_reset'), {'email': 'p1@test.com'})
        self.assertRedirects(resp, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

        message = mail.outbox[0]
        self.assertEqual(message.to, ['p1@test.com'])
        self.assertTrue(
            any(mimetype == 'text/html' for _, mimetype in message.alternatives),
            'reset email must carry an HTML alternative',
        )

        match = re.search(r'https?://[^/\s]+/reset/[^/\s]+/[^/\s]+', message.body)
        self.assertIsNotNone(match, 'reset link missing from the email body')
        link = match.group(0)

        # Open the link and choose a new password
        resp = self.client.get(link, follow=True)
        self.assertEqual(resp.status_code, 200)
        action_path = resp.request['PATH_INFO']
        resp = self.client.post(action_path, {
            'new_password1': 'Fresh@Pass1234',
            'new_password2': 'Fresh@Pass1234',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Password Changed')

        # Old password stopped working, new one works
        self.assertFalse(self.client.login(username='partner1', password='pass1234'))
        self.assertTrue(self.client.login(username='partner1', password='Fresh@Pass1234'))

    def test_unknown_email_uses_same_done_page_and_sends_nothing(self):
        resp = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(resp, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_user_gets_no_email(self):
        self.partner_user.is_active = False
        self.partner_user.save()
        resp = self.client.post(reverse('password_reset'), {'email': 'p1@test.com'})
        self.assertRedirects(resp, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_throttled_after_five_requests_from_same_ip(self):
        for _ in range(5):
            self.client.post(reverse('password_reset'), {'email': 'p1@test.com'})
        self.assertEqual(len(mail.outbox), 5)

        resp = self.client.post(reverse('password_reset'), {'email': 'p1@test.com'})
        self.assertEqual(resp.status_code, 200)  # stayed on the form
        self.assertContains(resp, 'Too many password reset requests')
        self.assertEqual(len(mail.outbox), 5)

    def test_pending_partner_can_open_reset_pages(self):
        self.login_as(self.unapproved_user)
        for url_name in ['password_reset', 'password_reset_done', 'password_reset_complete']:
            with self.subTest(url=url_name):
                resp = self.client.get(reverse(url_name))
                self.assertEqual(resp.status_code, 200)

    def test_change_password_page_still_works_for_pending_partner(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('password_change'))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(reverse('password_change'), {
            'old_password': 'pass1234',
            'new_password1': 'Changed@Pass1234',
            'new_password2': 'Changed@Pass1234',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.client.login(username='unapproved', password='Changed@Pass1234'))


# =================================================================
# PHASE 1B  BREVO HTTPS API EMAIL BACKEND
# =================================================================

class BrevoEmailBackendTests(TestCase):
    """BrevoAPIEmailBackend posts JSON to Brevo without ever leaking the key."""

    API_KEY = 'brevo-test-key-not-real'

    def _message(self):
        from django.core.mail import EmailMultiAlternatives
        message = EmailMultiAlternatives(
            subject='Reset your Partner Portal password',
            body='Plain text version of the message.',
            from_email='Partner Portal <no-reply@example.com>',
            to=['recipient@example.com'],
        )
        message.attach_alternative('<p>HTML version of the message.</p>', 'text/html')
        return message

    @override_settings(BREVO_API_KEY='brevo-test-key-not-real')
    def test_posts_json_with_expected_headers_and_payload(self):
        from core import email_backends

        mocked_response = mock.MagicMock()
        mocked_response.__enter__.return_value.read.return_value = b'{"message": "accepted"}'
        mocked_response.__enter__.return_value.getcode.return_value = 201

        with mock.patch.object(
            email_backends.urllib.request, 'urlopen', return_value=mocked_response
        ) as urlopen:
            sent = email_backends.BrevoAPIEmailBackend().send_messages([self._message()])

        self.assertEqual(sent, 1)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header('Api-key'), self.API_KEY)
        self.assertEqual(request.get_header('Accept'), 'application/json')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(urlopen.call_args[1].get('timeout'), 10)

        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['sender'], {'name': 'Partner Portal', 'email': 'no-reply@example.com'})
        self.assertEqual(payload['to'], [{'email': 'recipient@example.com'}])
        self.assertEqual(payload['subject'], 'Reset your Partner Portal password')
        self.assertEqual(payload['textContent'], 'Plain text version of the message.')
        self.assertEqual(payload['htmlContent'], '<p>HTML version of the message.</p>')

    @override_settings(BREVO_API_KEY='brevo-test-key-not-real')
    def test_http_error_logs_without_key_and_raises(self):
        from core import email_backends

        error = urllib.error.HTTPError(
            email_backends.BREVO_API_URL, 401, 'Unauthorized', {},
            io.BytesIO(b'{"code":401,"message":"Access denied, invalid key provided"}'),
        )
        with mock.patch.object(email_backends.urllib.request, 'urlopen', side_effect=error):
            with self.assertLogs('core.email_backends', level='ERROR') as captured:
                with self.assertRaises(urllib.error.HTTPError):
                    email_backends.BrevoAPIEmailBackend().send_messages([self._message()])

        output = '\n'.join(captured.output)
        self.assertIn('401', output)
        self.assertIn('Access denied', output)
        self.assertNotIn(self.API_KEY, output)

    @override_settings(BREVO_API_KEY='brevo-test-key-not-real')
    def test_network_error_fail_silently_returns_zero(self):
        from core import email_backends

        with mock.patch.object(
            email_backends.urllib.request, 'urlopen', side_effect=OSError('network unreachable')
        ):
            sent = email_backends.BrevoAPIEmailBackend(fail_silently=True).send_messages([self._message()])
        self.assertEqual(sent, 0)

    @override_settings(BREVO_API_KEY='')
    def test_missing_api_key_raises(self):
        from core import email_backends

        with self.assertRaises(ImproperlyConfigured):
            email_backends.BrevoAPIEmailBackend().send_messages([self._message()])

    def test_send_test_email_command_sends(self):
        out = io.StringIO()
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            call_command('send_test_email', 'someone@example.com', stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['someone@example.com'])
        self.assertIn('Success', out.getvalue())

    @override_settings(
        EMAIL_BACKEND='core.email_backends.BrevoAPIEmailBackend',
        BREVO_API_KEY='brevo-test-key-not-real',
    )
    def test_send_test_email_command_reports_errors_without_key(self):
        from core import email_backends

        error = urllib.error.HTTPError(
            email_backends.BREVO_API_URL, 401, 'Unauthorized', {},
            io.BytesIO(b'{"message":"Access denied"}'),
        )
        with mock.patch.object(email_backends.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(CommandError) as ctx:
                call_command('send_test_email', 'someone@example.com', stdout=io.StringIO())
        self.assertNotIn(self.API_KEY, str(ctx.exception))
