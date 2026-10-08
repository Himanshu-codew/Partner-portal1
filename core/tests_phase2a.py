"""
Phase 2A Test Suite
===================
Covers:
  * Ticket reply thread (views, permissions, forms, backfill migration)
  * Notification service (channels, dedupe, quota, logging, never-raises)
  * Event hooks (lead/order status, commission, approval, announcements)
  * WhatsApp / notification preference fields and validation

Run with:
    python manage.py test core.tests_phase2a --verbosity=2
"""

import importlib

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.db import models
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import PartnerProfileUpdateForm
from core.models import NotificationLog
from core.services import ChannelResult, notify
from core.services.notifications import EVENTS
from core.tests import BaseTestCase
from core.utils import normalize_phone
from partners.forms import PartnerProfileForm
from partners.models import PartnerProfile
from portal_content.models import Announcement
from portal_content.views import get_announcement_recipients
from support.forms import TicketReplyForm
from support.models import Ticket, TicketReply


# =================================================================
# normalize_phone
# =================================================================

class NormalizePhoneTests(TestCase):

    def test_national_number(self):
        self.assertEqual(normalize_phone('9876543210'), '+919876543210')

    def test_national_number_with_trunk_zero(self):
        self.assertEqual(normalize_phone('09876543210'), '+919876543210')

    def test_formatting_characters_are_stripped(self):
        self.assertEqual(normalize_phone('98765 43-210'), '+919876543210')
        self.assertEqual(normalize_phone('(98765) 43.210'), '+919876543210')

    def test_already_international(self):
        self.assertEqual(normalize_phone('+919876543210'), '+919876543210')

    def test_country_code_prefix_without_plus(self):
        self.assertEqual(normalize_phone('919876543210'), '+919876543210')

    def test_international_dialing_prefix(self):
        self.assertEqual(normalize_phone('00919876543210'), '+919876543210')

    def test_custom_default_country_code(self):
        self.assertEqual(normalize_phone('1234567890', '44'), '+441234567890')
        self.assertEqual(normalize_phone('+441234567890', '44'), '+441234567890')

    def test_too_short_rejected(self):
        with self.assertRaises(Exception):
            normalize_phone('123')

    def test_letters_rejected(self):
        with self.assertRaises(Exception):
            normalize_phone('call-me-now')

    def test_empty_rejected(self):
        for value in ('', '   ', None):
            with self.assertRaises(Exception):
                normalize_phone(value)

    def test_too_long_rejected(self):
        with self.assertRaises(Exception):
            normalize_phone('+9112345678901234')

    def test_e164_length_cap(self):
        # 10 digits after a long country code pushes E.164 past 15 digits.
        with self.assertRaises(Exception):
            normalize_phone('12345678901234', '999')


# =================================================================
# Ticket reply thread — permissions & behaviour
# =================================================================

class TicketReplyThreadTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.ticket = self.make_ticket()

    def _reply_url(self, ticket=None):
        return reverse('ticket_reply', args=[(ticket or self.ticket).pk])

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_unapproved_partner_blocked_by_middleware(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('approval', resp['Location'])

    def test_staff_can_view_any_ticket(self):
        self.login_as(self.staff)
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.ticket.description)

    def test_owner_can_view_ticket(self):
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_other_partner_redirected_away(self):
        ticket2 = self.make_ticket(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('ticket_detail', args=[ticket2.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/support/', resp['Location'])

    def test_partner_can_reply_to_open_ticket(self):
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(self._reply_url(), {'message': 'Still waiting for an update.'})
        self.assertEqual(resp.status_code, 302)
        reply = TicketReply.objects.get(ticket=self.ticket)
        self.assertEqual(reply.author, self.partner_user)
        self.assertEqual(reply.source, 'portal')
        self.assertEqual(reply.message, 'Still waiting for an update.')

    def test_partner_reply_sends_no_email(self):
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(), {'message': 'Any news?'})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificationLog.objects.count(), 0)

    @override_settings(WHATSAPP_ENABLED=False)
    def test_staff_reply_notifies_partner(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(self._reply_url(), {'message': 'All fixed now.'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['p1@test.com'])
        self.assertEqual(message.subject, EVENTS['ticket_reply'])
        self.assertIn('All fixed now.', message.body)
        self.assertIn(self.ticket.subject, message.body)

        email_log = NotificationLog.objects.get(channel='email')
        self.assertEqual(email_log.event, 'ticket_reply')
        self.assertEqual(email_log.status, 'sent')
        whatsapp_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(whatsapp_log.status, 'skipped')
        self.assertEqual(whatsapp_log.error, 'not configured')

    def test_get_on_reply_is_405(self):
        self.login_as(self.staff)
        resp = self.client.get(self._reply_url())
        self.assertEqual(resp.status_code, 405)

    def test_reply_requires_message(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(), {'message': ''})
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_reply_rejects_overlong_message(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(), {'message': 'x' * 5001})
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_reply_message_max_length_is_enforced_by_form(self):
        form = TicketReplyForm(data={'message': 'x' * 5000})
        self.assertTrue(form.is_valid())
        form = TicketReplyForm(data={'message': 'x' * 5001})
        self.assertFalse(form.is_valid())

    def test_partner_cannot_reply_to_closed_ticket(self):
        self.ticket.status = 'CLOSED'
        self.ticket.save()
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(self._reply_url(), {'message': 'Reopening?'}, follow=True)
        self.assertEqual(TicketReply.objects.count(), 0)
        self.assertContains(resp, 'closed')

    def test_staff_can_reply_to_closed_ticket(self):
        self.ticket.status = 'CLOSED'
        self.ticket.save()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(), {'message': 'One last note.'})
        self.assertEqual(TicketReply.objects.count(), 1)

    def test_partner_cannot_reply_to_other_partner_ticket(self):
        ticket2 = self.make_ticket(partner=self.partner_profile2)
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(ticket2), {'message': 'sneaky'})
        self.assertEqual(TicketReply.objects.count(), 0)

    def test_closed_ticket_hides_reply_form(self):
        self.ticket.status = 'CLOSED'
        self.ticket.save()
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertContains(resp, 'This ticket is closed')
        self.assertNotContains(resp, 'Send Reply')

    def test_detail_shows_reply_thread(self):
        TicketReply.objects.create(ticket=self.ticket, author=self.staff, message='First answer')
        TicketReply.objects.create(ticket=self.ticket, author=self.partner_user, message='Thanks!')
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('ticket_detail', args=[self.ticket.pk]))
        self.assertContains(resp, 'First answer')
        self.assertContains(resp, 'Thanks!')

    def test_ticket_list_links_to_detail_and_badges_replies(self):
        self.login_as(self.staff)
        resp = self.client.get(reverse('ticket_list'))
        self.assertContains(resp, f'/support/{self.ticket.pk}/')
        self.assertNotContains(resp, 'Replied')

        TicketReply.objects.create(ticket=self.ticket, author=self.staff, message='hello')
        resp = self.client.get(reverse('ticket_list'))
        self.assertContains(resp, 'Replied')

    def test_reply_bumps_updated_at(self):
        before = self.ticket.updated_at
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._reply_url(), {'message': 'bump'})
        self.ticket.refresh_from_db()
        self.assertGreater(self.ticket.updated_at, before)


# =================================================================
# Legacy admin_reply backfill migration
# =================================================================

class _PlainManagerProxy:
    """Stand-in for a historical model: same table, plain manager.

    Historical migration models never keep custom managers (unless
    use_in_migrations=True), so the real migration sees soft-deleted
    rows too. This reproduces that behaviour for the real model classes.
    """

    def __init__(self, model):
        self._model = model
        manager = models.Manager()
        manager.model = model
        manager.name = 'objects'
        self.objects = manager


class _HistoricalApps:
    def get_model(self, app_label, model_name):
        from django.apps import apps as real_apps
        return _PlainManagerProxy(real_apps.get_model(app_label, model_name))


def _run_backfill():
    migration = importlib.import_module('support.migrations.0005_backfill_admin_replies')
    migration.backfill_admin_replies(_HistoricalApps(), None)


class AdminReplyBackfillTests(TestCase):

    def test_backfills_legacy_reply(self):
        ticket = Ticket.objects.create(
            partner=self._make_profile(),
            subject='Legacy',
            description='old',
            admin_reply='We fixed it.',
        )
        expected_updated_at = ticket.updated_at
        ticket.refresh_from_db()

        _run_backfill()

        reply = TicketReply.objects.get(ticket=ticket)
        self.assertEqual(reply.message, 'We fixed it.')
        self.assertIsNone(reply.author)
        self.assertEqual(reply.source, 'portal')
        self.assertEqual(reply.created_at, expected_updated_at)

    def test_skips_tickets_without_reply(self):
        ticket = Ticket.objects.create(
            partner=self._make_profile(),
            subject='No reply yet',
            description='...',
        )
        Ticket.objects.filter(pk=ticket.pk).update(admin_reply='')

        _run_backfill()

        self.assertEqual(TicketReply.objects.count(), 0)

    def test_includes_soft_deleted_tickets(self):
        profile = self._make_profile()
        deleted = Ticket.objects.create(
            partner=profile, subject='Deleted', description='...', admin_reply='bye'
        )
        deleted.soft_delete()

        _run_backfill()

        self.assertEqual(TicketReply.objects.filter(ticket=deleted).count(), 1)

    def _make_profile(self):
        user = User.objects.create_user(
            username=f'bf{User.objects.count()}', password='x', email='bf@test.com'
        )
        return PartnerProfile.objects.create(
            user=user, company_name='Backfill Co', phone_number='9876543210', is_approved=True
        )


# =================================================================
# Notification service
# =================================================================

class NotificationServiceTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.ticket = self.make_ticket()
        self.reply = TicketReply.objects.create(
            ticket=self.ticket, author=self.staff, message='We are on it.'
        )

    def test_channel_result_rendering(self):
        self.assertEqual(str(ChannelResult('sent')), 'sent')
        self.assertEqual(str(ChannelResult('failed', 'boom')), 'failed: boom')

    @override_settings(WHATSAPP_ENABLED=False)
    def test_delivers_email_and_logs_both_channels(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = notify(
                self.partner_user, 'ticket_reply',
                {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff},
            )
        self.assertEqual(result.status, 'queued')
        self.assertEqual(len(mail.outbox), 1)

        email_log = NotificationLog.objects.get(channel='email')
        self.assertEqual(email_log.status, 'sent')
        self.assertEqual(email_log.error, '')
        whatsapp_log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(whatsapp_log.status, 'skipped')
        self.assertEqual(whatsapp_log.error, 'not configured')

    def test_renders_html_alternative(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        self.assertTrue(mail.outbox[0].alternatives)

    def test_unknown_event_skipped(self):
        result = notify(self.partner_user, 'nonsense_event')
        self.assertEqual(result.status, 'skipped')
        self.assertEqual(result.error, 'unknown event')

    def test_actor_is_never_notified(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = notify(
                self.partner_user, 'ticket_reply',
                {'ticket': self.ticket, 'reply': self.reply, 'actor': self.partner_user},
            )
        self.assertEqual(result.status, 'skipped')
        self.assertEqual(result.error, 'actor is recipient')
        self.assertEqual(len(mail.outbox), 0)

    def test_unapproved_partner_skipped(self):
        result = notify(self.unapproved_user, 'ticket_reply', {'ticket': self.ticket})
        self.assertEqual(result.status, 'skipped')
        self.assertEqual(result.error, 'partner not approved')

    def test_inactive_user_skipped(self):
        self.partner_user.is_active = False
        self.partner_user.save()
        result = notify(self.partner_user, 'ticket_reply', {'ticket': self.ticket})
        self.assertEqual(result.status, 'skipped')
        self.assertEqual(result.error, 'inactive user')

    def test_missing_email_skipped(self):
        user = User.objects.create_user(username='noemail', password='x', email='')
        with self.captureOnCommitCallbacks(execute=True):
            notify(user, 'ticket_reply', {'ticket': self.ticket})
        log = NotificationLog.objects.get(user=user, channel='email')
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error, 'no email address')

    def test_email_preference_opt_out(self):
        self.partner_profile.notify_email = False
        self.partner_profile.save()
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        self.assertEqual(len(mail.outbox), 0)
        log = NotificationLog.objects.get(channel='email')
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error, 'email notifications disabled')

    def test_staff_without_profile_still_gets_email(self):
        announcement = Announcement.objects.create(title='Hello', content='World')
        with self.captureOnCommitCallbacks(execute=True):
            result = notify(self.staff, 'announcement_published', {'announcement': announcement})
        self.assertEqual(result.status, 'queued')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['staff@test.com'])

    def test_dedupe_suppresses_identical_event(self):
        lead = self.make_lead()
        with self.captureOnCommitCallbacks(execute=True):
            first = notify(self.partner_user, 'lead_status_changed', {'lead': lead, 'actor': self.staff})
        with self.captureOnCommitCallbacks(execute=True):
            second = notify(self.partner_user, 'lead_status_changed', {'lead': lead, 'actor': self.staff})
        self.assertEqual(first.status, 'queued')
        self.assertEqual(second.status, 'skipped')
        self.assertEqual(second.error, 'duplicate')
        self.assertEqual(len(mail.outbox), 1)

    def test_different_context_is_not_deduped(self):
        lead_a = self.make_lead()
        lead_b = self.make_lead()
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'lead_status_changed', {'lead': lead_a, 'actor': self.staff})
            notify(self.partner_user, 'lead_status_changed', {'lead': lead_b, 'actor': self.staff})
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(NOTIFY_EMAIL_DAILY_LIMIT=1)
    def test_daily_email_limit(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
            notify(self.partner_profile2.user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        self.assertEqual(len(mail.outbox), 1)
        logs = NotificationLog.objects.filter(channel='email').order_by('created_at')
        self.assertEqual(logs[0].status, 'sent')
        self.assertEqual(logs[1].status, 'skipped')
        self.assertEqual(logs[1].error, 'daily email limit reached')

    @override_settings(WHATSAPP_ENABLED=True, TWILIO_ACCOUNT_SID='',
                       TWILIO_AUTH_TOKEN='', TWILIO_WHATSAPP_FROM='')
    def test_whatsapp_enabled_but_settings_missing(self):
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.whatsapp_opt_in_at = timezone.now()
        self.partner_profile.whatsapp_number = '+919876543210'
        self.partner_profile.notify_whatsapp = True
        self.partner_profile.save()

        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error, 'not configured')

    @override_settings(WHATSAPP_ENABLED=True)
    def test_whatsapp_respects_consent(self):
        self.partner_profile.notify_whatsapp = False
        self.partner_profile.save()
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.partner_user, 'ticket_reply',
                   {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        log = NotificationLog.objects.get(channel='whatsapp')
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error, 'whatsapp notifications disabled')

    def test_delivery_failure_is_logged_not_raised(self):
        from unittest import mock
        with mock.patch(
            'core.services.notifications.send_mail',
            side_effect=RuntimeError('smtp exploded'),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(self.partner_user, 'ticket_reply',
                                {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        self.assertEqual(result.status, 'queued')
        log = NotificationLog.objects.get(channel='email')
        self.assertEqual(log.status, 'failed')
        self.assertIn('smtp exploded', log.error)
        self.assertLessEqual(len(log.error), 200)

    def test_secrets_are_redacted_from_logged_errors(self):
        from unittest import mock
        with override_settings(BREVO_API_KEY='super-secret-key'):
            with mock.patch(
                'core.services.notifications.send_mail',
                side_effect=RuntimeError('boom while using super-secret-key'),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    notify(self.partner_user, 'ticket_reply',
                           {'ticket': self.ticket, 'reply': self.reply, 'actor': self.staff})
        log = NotificationLog.objects.get(channel='email')
        self.assertNotIn('super-secret-key', log.error)
        self.assertIn('[redacted]', log.error)


# =================================================================
# Event hooks wired into existing views
# =================================================================

class EventHookTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_lead_status_change_notifies_partner(self):
        lead = self.make_lead()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('lead_update_status', args=[lead.pk]), {'status': 'CONVERTED'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['p1@test.com'])
        self.assertEqual(mail.outbox[0].subject, EVENTS['lead_status_changed'])
        log = NotificationLog.objects.get(event='lead_status_changed', channel='email')
        self.assertEqual(log.status, 'sent')

    def test_lead_status_unchanged_sends_nothing(self):
        lead = self.make_lead()  # status NEW
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('lead_update_status', args=[lead.pk]), {'status': 'NEW'})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_order_status_change_notifies_partner(self):
        order = self.make_order()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('order_update_status', args=[order.pk]), {'status': 'COMPLETED'})
        self.assertEqual(len(mail.outbox), 1)
        log = NotificationLog.objects.get(event='order_status_changed', channel='email')
        self.assertEqual(log.status, 'sent')

    def test_order_status_unchanged_sends_nothing(self):
        order = self.make_order()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('order_update_status', args=[order.pk]), {'status': order.status})
        self.assertEqual(len(mail.outbox), 0)

    def test_commission_paid_notifies_partner(self):
        order = self.make_order()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('order_mark_commission_paid', args=[order.pk]))
        self.assertEqual(len(mail.outbox), 1)
        log = NotificationLog.objects.get(event='commission_paid', channel='email')
        self.assertEqual(log.status, 'sent')

    def test_commission_marked_unpaid_sends_nothing(self):
        order = self.make_order()
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('order_mark_commission_unpaid', args=[order.pk]))
        self.assertEqual(len(mail.outbox), 0)

    def test_partner_approval_sends_welcome_email(self):
        self.login_as(self.staff)
        url = reverse('partner_approve', args=[self.unapproved_profile.pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'is_approved': 'true'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['un@test.com'])
        log = NotificationLog.objects.get(event='partner_approval_changed', channel='email')
        self.assertEqual(log.status, 'sent')

    def test_partner_rejection_sends_nothing(self):
        self.partner_profile.is_approved = False
        self.partner_profile.save()
        self.login_as(self.staff)
        url = reverse('partner_approve', args=[self.partner_profile.pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'is_approved': 'false'})
        self.assertEqual(len(mail.outbox), 0)


# =================================================================
# Announcements
# =================================================================

class AnnouncementNotificationTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_notifies_all_approved_active_partners(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse('announcement_create'), {
                'title': 'Festive Offer',
                'content': 'Enjoy 20% off this season.',
                'is_active': True,
            })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ['p1@test.com', 'p2@test.com'],
        )
        self.assertEqual(
            NotificationLog.objects.filter(
                event='announcement_published', channel='email', status='sent'
            ).count(),
            2,
        )

    def test_private_announcement_only_notifies_selected_partner(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('announcement_create'), {
                'title': 'Private note',
                'content': 'Only for Beta.',
                'is_active': True,
                'visible_to': [self.partner_profile2.pk],
            })
        self.assertEqual([m.to[0] for m in mail.outbox], ['p2@test.com'])

    def test_get_announcement_recipients_visibility(self):
        public = Announcement.objects.create(title='Public', content='all')
        private = Announcement.objects.create(title='Private', content='one')
        private.visible_to.add(self.partner_profile2)

        public_ids = [p.pk for p in get_announcement_recipients(public)]
        private_ids = [p.pk for p in get_announcement_recipients(private)]

        self.assertIn(self.partner_profile.pk, public_ids)
        self.assertIn(self.partner_profile2.pk, public_ids)
        self.assertNotIn(self.unapproved_profile.pk, public_ids)
        self.assertEqual(private_ids, [self.partner_profile2.pk])

    def test_recipient_list_is_capped(self):
        users = [
            User(username=f'bulk{i}', email=f'bulk{i}@t.com')
            for i in range(205)
        ]
        User.objects.bulk_create(users)
        users = list(User.objects.filter(username__startswith='bulk'))
        PartnerProfile.objects.bulk_create([
            PartnerProfile(
                user=user, company_name=f'Bulk Co {i}',
                phone_number='9000000000', is_approved=True,
            )
            for i, user in enumerate(users)
        ])

        announcement = Announcement.objects.create(title='Cap', content='x')
        self.assertEqual(len(get_announcement_recipients(announcement)), 200)


# =================================================================
# WhatsApp / notification preference fields
# =================================================================

class WhatsAppPreferenceTests(BaseTestCase):

    def _form_data(self, **overrides):
        data = {
            'company_name': 'Acme Corp',
            'phone_number': '9876543210',
            'address': '',
            'whatsapp_number': '+919876543211',
            'whatsapp_opt_in': True,
            'notify_email': True,
            'notify_whatsapp': False,
        }
        data.update(overrides)
        return data

    def test_number_is_normalized_and_consent_stamped(self):
        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_number='098765 43211'),
        )
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save()
        self.assertEqual(profile.whatsapp_number, '+919876543211')
        self.assertIsNotNone(profile.whatsapp_opt_in_at)
        self.assertTrue(profile.notify_email)

    def test_opt_in_without_number_is_rejected(self):
        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_number=''),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('whatsapp_number', form.errors)

    def test_invalid_number_is_rejected(self):
        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_number='not-a-number'),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('whatsapp_number', form.errors)

    def test_duplicate_whatsapp_number_is_rejected(self):
        self.partner_profile2.whatsapp_number = '+919876543212'
        self.partner_profile2.save()
        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_number='9876543212'),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('whatsapp_number', form.errors)

    def test_blank_number_without_opt_in_is_valid(self):
        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_number='', whatsapp_opt_in=False),
        )
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save()
        self.assertEqual(profile.whatsapp_number, '')
        self.assertIsNone(profile.whatsapp_opt_in_at)

    def test_opting_out_clears_consent_timestamp(self):
        self.partner_profile.whatsapp_number = '+919876543211'
        self.partner_profile.whatsapp_opt_in = True
        self.partner_profile.whatsapp_opt_in_at = timezone.now()
        self.partner_profile.save()

        form = PartnerProfileUpdateForm(
            instance=self.partner_profile,
            data=self._form_data(whatsapp_opt_in=False),
        )
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save()
        self.assertFalse(profile.whatsapp_opt_in_at)
        self.assertIsNone(profile.whatsapp_opt_in_at)

    def test_admin_profile_form_accepts_new_fields(self):
        admin_user = User.objects.create_user(
            username='newpartner', password='x', email='np@test.com'
        )
        form = PartnerProfileForm(data={
            'user': admin_user.pk,
            'company_name': 'New Co',
            'phone_number': '9876543200',
            'address': '',
            'is_approved': False,
            'whatsapp_number': '9876543210',
            'whatsapp_opt_in': True,
            'notify_email': True,
            'notify_whatsapp': True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save()
        self.assertEqual(profile.whatsapp_number, '+919876543210')
        self.assertIsNotNone(profile.whatsapp_opt_in_at)


# =================================================================
# In-app bell feed
# =================================================================

class NotificationFeedTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.ticket = self.make_ticket()

    def test_staff_sees_partner_reply_entry(self):
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('ticket_reply', args=[self.ticket.pk]),
                             {'message': 'Any update on this?'})

        self.login_as(self.staff)
        data = self.client.get(reverse('notifications_feed')).json()
        entries = [n for n in data['notifications'] if n['icon'] == 'bi-reply-fill']
        self.assertTrue(any(n['title'] == self.ticket.subject for n in entries))
        self.assertTrue(any('Reply from partner1' in n['msg'] for n in entries))
        self.assertTrue(any(n['url'] == f'/support/{self.ticket.pk}/' for n in entries))

    def test_partner_sees_staff_reply_entry(self):
        self.login_as(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('ticket_reply', args=[self.ticket.pk]),
                             {'message': 'Here is your answer.'})

        self.login_as(self.partner_user)
        data = self.client.get(reverse('notifications_feed')).json()
        entries = [n for n in data['notifications'] if n['title'] == self.ticket.subject]
        self.assertTrue(any(n['msg'].startswith('Admin replied') for n in entries))

    def test_partner_own_reply_not_flagged_as_admin_reply(self):
        self.login_as(self.partner_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('ticket_reply', args=[self.ticket.pk]),
                             {'message': 'My own follow-up.'})

        data = self.client.get(reverse('notifications_feed')).json()
        entries = [n for n in data['notifications'] if n['title'] == self.ticket.subject]
        self.assertFalse(any(n['msg'].startswith('Admin replied') for n in entries))
