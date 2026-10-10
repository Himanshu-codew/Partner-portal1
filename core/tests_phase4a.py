"""Phase 4A — PWA (manifest, service worker, offline) and mobile usability.

The service worker is asserted *on its source text* — we must never run
arbitrary SW code in a test. Nothing here touches the network.
"""

import json
import re

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from core.tests import BaseTestCase


def _get(source, var):
    """Extract the value of a `const var = <value>;` line from JS source."""
    match = re.search(
        r'const\s+%s\s*=\s*(.+?);' % re.escape(var), source, re.DOTALL
    )
    if not match:
        raise AssertionError('const %s not found in source' % var)
    return match.group(1).strip()


class ManifestTests(BaseTestCase):
    """/manifest.webmanifest is valid, points at real icons, is public."""

    def test_manifest_is_valid_json_with_required_keys(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'].split(';')[0].strip(),
            'application/manifest+json',
        )
        manifest = json.loads(response.content)
        for key in ('name', 'short_name', 'start_url', 'scope', 'display',
                    'background_color', 'theme_color', 'icons'):
            self.assertIn(key, manifest)
        self.assertEqual(manifest['name'], 'Partner Portal')
        self.assertEqual(manifest['short_name'], 'Portal')
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['scope'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['theme_color'], '#1e293b')
        self.assertEqual(manifest['background_color'], '#0f172a')

        sizes = [icon['sizes'] for icon in manifest['icons']]
        self.assertIn('192x192', sizes)
        self.assertIn('512x512', sizes)
        purposes = {icon.get('purpose') for icon in manifest['icons']}
        self.assertIn('maskable', purposes)

    def test_manifest_icon_files_exist(self):
        manifest = json.loads(self.client.get('/manifest.webmanifest').content)
        for icon in manifest['icons']:
            # src looks like /static/icons/... — strip the URL prefix and any
            # content-hash segment (manifest storage in production).
            src = icon['src']
            path = src.split('/static/', 1)[-1]
            self.assertIsNotNone(
                finders.find(path),
                'icon file referenced by manifest does not exist: %s' % src,
            )

    def test_manifest_is_reachable_anonymously(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)

    def test_manifest_is_reachable_by_pending_partner(self):
        self.login_as(self.unapproved_user)
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('approval-pending', response.url if hasattr(response, 'url') else '')


class ServiceWorkerTests(BaseTestCase):
    """/service-worker.js headers, reachability and caching policy."""

    def get_sw(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        return response

    def test_sw_content_type_and_headers(self):
        response = self.get_sw()
        self.assertEqual(
            response['Content-Type'].split(';')[0].strip(), 'application/javascript'
        )
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertEqual(response['Cache-Control'], 'no-cache')

    def test_sw_is_reachable_anonymously(self):
        self.assertEqual(self.get_sw().status_code, 200)

    def test_sw_is_reachable_by_pending_partner(self):
        self.login_as(self.unapproved_user)
        self.assertEqual(self.get_sw().status_code, 200)

    def test_sw_precaches_only_offline_and_core_static_assets(self):
        source = self.get_sw().content.decode('utf-8')
        precache = json.loads(_get(source, 'PRECACHE_URLS'))
        self.assertIn('/offline/', precache)
        self.assertEqual(precache[0], '/offline/')
        self.assertTrue(all(
            url.startswith('/static/')
            or url in ('/offline/', '/manifest.webmanifest')
            for url in precache
        ), 'precache must only contain the offline page, manifest and static assets')

    def test_sw_network_only_navigation_rule(self):
        source = self.get_sw().content.decode('utf-8')
        # Navigations must be network-only with an offline fallback...
        self.assertIn("request.mode === 'navigate'", source)
        self.assertIn('fetch(request).catch(() => caches.match(OFFLINE_URL))', source)
        # ...and must never be cached: no cache.put on the navigate path.
        nav_start = source.index("request.mode === 'navigate'")
        static_start = source.index("startsWith('/static/')")
        between = source[nav_start:static_start]
        self.assertNotIn('cache.put(', between)

    def test_sw_ignores_non_get_requests(self):
        source = self.get_sw().content.decode('utf-8')
        self.assertIn("request.method !== 'GET'", source)
        guard = source[
            source.index("request.method !== 'GET'")
            : source.index("request.mode === 'navigate'")
        ]
        self.assertIn('return;', guard)
        self.assertNotIn('cache.', guard)

    def test_sw_stale_while_revalidate_only_for_static(self):
        source = self.get_sw().content.decode('utf-8')
        self.assertIn("startsWith('/static/')", source)
        self.assertIn('cache.put(request, response.clone())', source)
        # Download/media/API paths are never special-cased for caching.
        self.assertNotIn("/media/", source)
        self.assertNotIn("/notifications/", source)

    def test_sw_versioned_cache_and_activate_cleanup(self):
        source = self.get_sw().content.decode('utf-8')
        self.assertRegex(source, r"CACHE_NAME\s*=\s*'partner-portal-")
        self.assertIn('caches.delete(key)', source)


class OfflinePageTests(BaseTestCase):
    """/offline/ is a public, branded fallback page."""

    def test_offline_page_is_public(self):
        response = self.client.get('/offline/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'offline.html')
        self.assertContains(response, 'Retry')
        self.assertContains(response, 'You\'re offline')

    def test_offline_page_accessible_by_pending_partner(self):
        self.login_as(self.unapproved_user)
        response = self.client.get('/offline/')
        self.assertEqual(response.status_code, 200)

    def test_offline_page_is_not_login_required(self):
        response = self.client.get(reverse('offline'))
        self.assertEqual(response.status_code, 200)


class BaseTemplatePWATests(BaseTestCase):
    """The base template wires up the manifest, theme color and SW."""

    def test_base_contains_manifest_theme_and_apple_tags(self):
        self.login_as(self.partner_user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'href="/manifest.webmanifest"')
        self.assertContains(response, 'name="theme-color"')
        self.assertContains(response, 'content="#1e293b"')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, 'name="apple-mobile-web-app-capable"')

    def test_base_registers_the_service_worker(self):
        self.login_as(self.partner_user)
        response = self.client.get('/')
        self.assertContains(response, "if ('serviceWorker' in navigator)")
        self.assertContains(response, "navigator.serviceWorker.register('/service-worker.js'")

    def test_auth_pages_include_manifest_and_theme_color(self):
        # The PWA head tags live in base.html so login/auth pages get them too.
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'name="theme-color"')