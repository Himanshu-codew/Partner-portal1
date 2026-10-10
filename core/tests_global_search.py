"""Phase 4B — global search.

Covers the top-bar search form, the grouped results page and the type-ahead
suggest endpoint. Permissions mirror the list views: staff see everything,
partners only their own records, and soft deleted rows never surface.
"""

from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from core.tests import BaseTestCase
from leads.models import Lead
from orders.models import Order
from support.models import Ticket
from partners.models import PartnerDocument


class GlobalSearchTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.lead1 = Lead.objects.create(
            partner=self.partner_profile, customer_name='Acme Widget Lead',
            customer_phone='9000000001', product_interest='Widgets',
        )
        self.lead2 = Lead.objects.create(
            partner=self.partner_profile2, customer_name='Beta Widget Lead',
            customer_phone='9000000002', product_interest='Widgets',
        )
        self.order1 = Order.objects.create(
            partner=self.partner_profile, lead=self.lead1,
            order_number='ORD-ACME-1', amount='100.00', commission_amount='10.00',
        )
        self.order2 = Order.objects.create(
            partner=self.partner_profile2, lead=self.lead2,
            order_number='ORD-BETA-1', amount='200.00', commission_amount='20.00',
        )
        self.ticket1 = Ticket.objects.create(
            partner=self.partner_profile, subject='Acme support issue',
            description='help please',
        )
        self.ticket2 = Ticket.objects.create(
            partner=self.partner_profile2, subject='Beta support issue',
            description='help please',
        )
        self.kyc1 = PartnerDocument.objects.create(
            partner=self.partner_profile, doc_type='PAN',
        )
        self.kyc2 = PartnerDocument.objects.create(
            partner=self.partner_profile2, doc_type='PAN',
        )

    # ── helpers ─────────────────────────────────────────────────

    def _search(self, query, user=None):
        if user is not None:
            self.login_as(user)
        return self.client.get(reverse('search'), {'q': query})

    def _group(self, resp, key):
        for g in resp.context['groups']:
            if g['key'] == key:
                return g
        return None

    # ── permissions ─────────────────────────────────────────────

    def test_partner_only_sees_own_leads(self):
        resp = self._search('Widget', user=self.partner_user)
        leads = self._group(resp, 'leads')
        titles = [i['title'] for i in leads['items']]
        self.assertIn('Acme Widget Lead', titles)
        self.assertNotIn('Beta Widget Lead', titles)

    def test_partner_only_sees_own_orders(self):
        resp = self._search('ORD', user=self.partner_user)
        orders = self._group(resp, 'orders')
        titles = [i['title'] for i in orders['items']]
        self.assertIn('Order #ORD-ACME-1', titles)
        self.assertNotIn('Order #ORD-BETA-1', titles)

    def test_partner_only_sees_own_tickets(self):
        resp = self._search('support issue', user=self.partner_user)
        tickets = self._group(resp, 'tickets')
        titles = [i['title'] for i in tickets['items']]
        self.assertIn('Acme support issue', titles)
        self.assertNotIn('Beta support issue', titles)

    def test_partner_only_sees_own_kyc(self):
        # Beta Ltd's documents must never appear for the Acme partner.
        resp = self._search('Beta', user=self.partner_user)
        self.assertIsNone(self._group(resp, 'kyc'))

        resp = self._search('Acme', user=self.partner_user)
        kyc = self._group(resp, 'kyc')
        self.assertEqual(len(kyc['items']), 1)
        self.assertIn('Acme Corp', kyc['items'][0]['title'])

    def test_staff_sees_all_leads(self):
        resp = self._search('Widget', user=self.staff)
        leads = self._group(resp, 'leads')
        titles = [i['title'] for i in leads['items']]
        self.assertIn('Acme Widget Lead', titles)
        self.assertIn('Beta Widget Lead', titles)

    def test_staff_has_partner_and_user_groups(self):
        resp = self._search('partner', user=self.staff)
        self.assertIsNotNone(self._group(resp, 'partners'))
        self.assertIsNotNone(self._group(resp, 'users'))

    def test_partner_has_no_partner_or_user_groups(self):
        resp = self._search('Corp', user=self.partner_user)
        self.assertIsNone(self._group(resp, 'partners'))
        self.assertIsNone(self._group(resp, 'users'))

    # ── soft delete + access ────────────────────────────────────

    def test_soft_deleted_items_excluded(self):
        self.lead1.soft_delete(self.staff)
        resp = self._search('Acme Widget', user=self.staff)
        self.assertIsNone(self._group(resp, 'leads'))

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse('search'), {'q': 'Widget'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/login/'))

    def test_unapproved_partner_blocked(self):
        self.login_as(self.unapproved_user)
        resp = self.client.get(reverse('search'), {'q': 'Widget'})
        self.assertRedirects(resp, reverse('approval_pending'))

    # ── query handling + escaping ───────────────────────────────

    def test_short_query_shows_hint_and_runs_no_search(self):
        resp = self._search('a', user=self.partner_user)
        self.assertEqual(resp.context['total'], 0)
        self.assertEqual(resp.context['groups'], [])
        self.assertContains(resp, 'at least 2 characters')

    def test_empty_query_shows_prompt(self):
        resp = self._search('', user=self.partner_user)
        self.assertEqual(resp.context['total'], 0)
        self.assertContains(resp, 'Type 2 or more characters')

    def test_html_in_lead_name_is_escaped_on_page(self):
        Lead.objects.create(
            partner=self.partner_profile,
            customer_name='<script>alert(1)</script>',
            customer_phone='9000000009', product_interest='Widgets',
        )
        resp = self._search('script', user=self.partner_user)
        self.assertContains(resp, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotIn(b'<script>alert(1)', resp.content)

    # ── suggest endpoint ────────────────────────────────────────

    def test_suggest_requires_login(self):
        resp = self.client.get(reverse('search_suggest'), {'q': 'Widget'})
        self.assertEqual(resp.status_code, 302)

    def test_suggest_respects_partner_isolation(self):
        self.login_as(self.partner_user)
        data = self.client.get(reverse('search_suggest'), {'q': 'Widget'}).json()
        titles = [
            i['title'] for g in data['groups'] for i in g['items']
        ]
        self.assertIn('Acme Widget Lead', titles)
        self.assertNotIn('Beta Widget Lead', titles)

    def test_suggest_short_query_returns_empty(self):
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('search_suggest'), {'q': 'a'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['groups'], [])

    def test_suggest_throttled_returns_429(self):
        self.login_as(self.partner_user)
        with mock.patch('core.views.SEARCH_SUGGEST_THROTTLE', 3):
            for _ in range(3):
                resp = self.client.get(reverse('search_suggest'), {'q': 'Widget'})
                self.assertEqual(resp.status_code, 200)
            resp = self.client.get(reverse('search_suggest'), {'q': 'Widget'})
        self.assertEqual(resp.status_code, 429)

    # ── top bar markup ──────────────────────────────────────────

    def test_topbar_has_form_with_name_q(self):
        self.login_as(self.partner_user)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="topbarSearchForm"')
        self.assertContains(resp, 'action="%s"' % reverse('search'))
        self.assertContains(resp, 'name="q"')
