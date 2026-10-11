from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.db import connections

import json
import os
from datetime import datetime

DEFAULT_ALIAS = 'default'


class Command(BaseCommand):
    help = (
        "Write a JSON backup with dumpdata (--all, natural foreign/primary keys), "
        "excluding contenttypes, auth.permission, admin.logentry and sessions. "
        "Output path may be specified with --output (default: backups/partner_backup_<UTC timestamp>.json). "
        "Refuses to overwrite an existing file. Never prints the database URL."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            '-o',
            help='Full path to write the JSON backup file.',
        )

    def handle(self, *args, **options):
        output_path = options.get('output') or self._default_output()
        abs_path = os.path.abspath(output_path)
        dir_path = os.path.dirname(abs_path) or '.'
        os.makedirs(dir_path, exist_ok=True)

        if os.path.exists(abs_path):
            raise CommandError(f"Backup file already exists and will not be overwritten: {abs_path}")

        self.stdout.write(f"Writing backup to: {abs_path}")

        # Neon/Postgres behind a pooler can drop server-side (named) cursors,
        # which dumpdata hits via queryset.iterator(). Force client-side
        # cursors for this connection and close it so the change takes effect.
        connection = connections[DEFAULT_ALIAS]
        original_disable = connection.settings_dict.get('DISABLE_SERVER_SIDE_CURSORS', False)
        connection.settings_dict['DISABLE_SERVER_SIDE_CURSORS'] = True
        connection.close()

        try:
            with open(abs_path, 'w', encoding='utf-8') as f:
                call_command(
                    'dumpdata',
                    '--all',
                    '--natural-foreign',
                    '--natural-primary',
                    '--exclude', 'contenttypes',
                    '--exclude', 'auth.permission',
                    '--exclude', 'admin.logentry',
                    '--exclude', 'sessions',
                    stdout=f,
                    format='json',
                )
        except Exception as exc:
            self._remove_partial(abs_path)
            raise CommandError(f"Backup failed: {exc}")
        finally:
            connection.settings_dict['DISABLE_SERVER_SIDE_CURSORS'] = original_disable
            connection.close()

        try:
            size_bytes = os.path.getsize(abs_path)
            with open(abs_path, 'r', encoding='utf-8') as f:
                record_count = len(json.load(f))
        except Exception as exc:
            self._remove_partial(abs_path)
            raise CommandError(f"Backup written but could not read it back: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Backup complete: {record_count} records, {size_bytes} bytes saved to {abs_path}"
        ))

    def _remove_partial(self, path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _default_output(self):
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        return os.path.join('backups', f'partner_backup_{ts}.json')
