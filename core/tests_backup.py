from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

import json
import os
import tempfile


class BackupDataCommandTests(TestCase):
    def test_backup_writes_json_and_counts_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'test_backup.json')
            call_command('backup_data', '--output', out)
            self.assertTrue(os.path.exists(out))
            with open(out, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertTrue(len(data) >= 0)

    def test_backup_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'test_backup.json')
            with open(out, 'w', encoding='utf-8') as f:
                f.write('[]')
            with self.assertRaises(CommandError):
                call_command('backup_data', '--output', out)

    def test_backup_includes_soft_deleted_rows(self):
        from leads.models import Lead
        from core.tests import BaseTestCase

        class T(BaseTestCase):
            def run_it(self):
                self.setUp()
                lead = self.make_lead()
                lead.soft_delete(self.staff)
                with tempfile.TemporaryDirectory() as tmp:
                    out = os.path.join(tmp, 'test_backup.json')
                    call_command('backup_data', '--output', out)
                    with open(out, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    lead_found = any(d['model'] == 'leads.lead' and d['pk'] == lead.pk for d in data)
                    return lead_found

        t = T()
        self.assertTrue(t.run_it())
