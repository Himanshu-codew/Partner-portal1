/* Partner Portal service worker (Phase 4A).
 *
 * Policy:
 *   - Precache ONLY the offline fallback page and core same-origin static assets.
 *   - Static assets under /static/  -> stale-while-revalidate.
 *   - Page navigations              -> NETWORK ONLY, falling back to /offline/.
 *   - Everything else (authenticated HTML, JSON/API, downloads, media) is
 *     never touched and never cached. Non-GET requests are ignored entirely.
 */
const CACHE_VERSION = '{{ cache_version }}';
const CACHE_NAME = 'partner-portal-' + CACHE_VERSION;
const OFFLINE_URL = '{{ offline_url }}';
const PRECACHE_URLS = {{ precache_urls_json|safe }};

/* ── Install: precache the offline page + core static assets ── */
self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE_NAME);
        // Cache entries individually so a single failure never aborts install.
        await Promise.all(PRECACHE_URLS.map(async (url) => {
            try {
                const response = await fetch(url, { cache: 'reload' });
                if (response && response.ok) {
                    await cache.put(url, response.clone());
                }
            } catch (err) {
                /* offline at install time — ignore, we retry on fetch */
            }
        }));
        await self.skipWaiting();
    })());
});

/* ── Activate: drop old cache versions ── */
self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(
            keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
        );
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (event) => {
    const request = event.request;

    // Never handle non-GET requests (POST forms, mutations, etc.).
    if (request.method !== 'GET') {
        return;
    }

    const url = new URL(request.url);

    // Leave cross-origin traffic (CDN CSS/JS, fonts, OCR provider) alone.
    if (url.origin !== self.location.origin) {
        return;
    }

    // Page navigations: NETWORK ONLY. Never serve stale authenticated HTML;
    // only fall back to the offline page when the network is unavailable.
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(() => caches.match(OFFLINE_URL))
        );
        return;
    }

    // Core static assets only: stale-while-revalidate.
    if (url.pathname.startsWith('/static/')) {
        event.respondWith((async () => {
            const cache = await caches.open(CACHE_NAME);
            const cached = await cache.match(request);
            const network = fetch(request).then((response) => {
                if (response && response.ok) {
                    cache.put(request, response.clone());
                }
                return response;
            }).catch(() => null);
            return cached || (await network) || Response.error();
        })());
        return;
    }

    // Everything else (authenticated pages, JSON/API, downloads, media):
    // plain network, never cached.
});
