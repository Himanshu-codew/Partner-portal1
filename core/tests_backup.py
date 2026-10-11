"""Tests for the ``backup_data`` management command."""

import json
import os
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TransactionTestCase

from leads.models import Lead
from partners.models import PartnerProfile

COMMAND_CALL = 'core.management.commands.backup_data.call_command'


class BackupDataCommandTests(TransactionTestCase):
    """Uses TransactionTestCase: the command closes the DB connection, which is
    unsafe inside the transaction wrapper that ``TestCase`` uses."""

    def _make_lead(self):
        user = User.objects.create_user(username='bk', password='pass1234')
        profile = PartnerProfile.objects.create(
            user=user, company_name='Backup Co', phone_number='9000000000',
            is_approved=True,
        )
        return Lead.objects.create(
            partner=profile, customer_name='Backup Lead',
            customer_phone='9123456789', product_interest='Software',
        )

    def test_server_side_cursors_disabled_during_run_and_restored(self):
        connection = connections['default']
        original = connection.settings_dict.get('DISABLE_SERVER_SIDE_CURSORS', False)
        observed = {}

        def fake_dumpdata(*args, **kwargs):
            observed['during'] = connection.settings_dict.get('DISABLE_SERVER_SIDE_CURSORS')
            kwargs['stdout'].write('[]')

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'backup.json')
            with mock.patch(COMMAND_CALL, side_effect=fake_dumpdata):
                call_command('backup_data', '--output', out)

        self.assertTrue(observed.get('during'))
        self.assertEqual(
            connection.settings_dict.get('DISABLE_SERVER_SIDE_CURSORS'), original
        )

    def test_failure_removes_partial_file(self):
        def boom(*args, **kwargs):
            kwargs['stdout'].write('[{"partial": true}')
            raise RuntimeError('cursor "_django_curs_1" does not exist')

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'backup.json')
            with mock.patch(COMMAND_CALL, side_effect=boom):
                with self.assertRaises(CommandError) as ctx:
                    call_command('backup_data', '--output', out)
            self.assertFalse(os.path.exists(out))

        message = str(ctx.exception)
        self.assertIn('does not exist', message)
        self.assertNotIn('postgres', message.lower())

    def test_success_writes_valid_json_including_soft_deleted(self):
        lead = self._make_lead()
        lead.soft_delete(User.objects.get(username='bk'))

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'backup.json')
            call_command('backup_data', '--output', out)
            self.assertTrue(os.path.exists(out))
            with open(out, 'r', encoding='utf-8') as f:
                data = json.load(f)

        self.assertIsInstance(data, list)
        self.assertTrue(
            any(d['model'] == 'leads.lead' and d['pk'] == lead.pk for d in data),
            'soft-deleted lead should be present in the backup',
        )

    def test_refuses_to_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'backup.json')
            with open(out, 'w', encoding='utf-8') as f:
                f.write('[]')
            with self.assertRaises(CommandError):
                call_command('backup_data', '--output', out)
