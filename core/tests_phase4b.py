"""Phase 4B — UI consistency polish.

Focus: the ticket list renders the status control exactly once. Previously
staff saw the status twice — a badge in the Status column *and* a dropdown in
the Actions column. It is now a single dropdown (staff) or a badge (partner).
"""

from django.urls import reverse

from core.tests import BaseTestCase


class TicketStatusControlTests(BaseTestCase):
    """The inline status control must not be duplicated per row."""

    def setUp(self):
        super().setUp()
        self.make_ticket()
        self.make_ticket()

    def test_staff_sees_one_status_form_per_row(self):
        self.login_as(self.staff)
        html = self.client.get(reverse('ticket_list')).content.decode()

        # One row-level status form per ticket, none in the Actions column.
        self.assertEqual(html.count('/support/update_status/'), 2)
        # The read-only badge (only shown to partners) is absent for staff.
        self.assertNotIn('bi-star me-1', html)

    def test_partner_sees_badge_not_status_form(self):
        self.login_as(self.partner_user)
        html = self.client.get(reverse('ticket_list')).content.decode()

        self.assertEqual(html.count('/support/update_status/'), 0)
        self.assertIn('bi-star me-1', html)
