# PWA & Mobile (Phase 4A)

The Partner Portal is an installable Progressive Web App. Everything here is
served by Django from the site root and is reachable **without logging in** and
**while a partner account is still pending approval** (see
`core/middleware.py`).

## Endpoints

| URL | View | Content-Type | Notes |
| --- | --- | --- | --- |
| `/manifest.webmanifest` | `core.views.web_manifest` | `application/manifest+json` | App metadata + icons |
| `/service-worker.js` | `core.views.service_worker` | `application/javascript` | `Service-Worker-Allowed: /`, `Cache-Control: no-cache` |
| `/offline/` | `core.views.offline` | `text/html` | Public branded fallback page |

Icons are generated into `static/icons/` and referenced with a leading-slash
static URL so they resolve from any page path.

### Regenerating the icons

Icons are produced by a **development-only** script (Pillow is an optional
dependency):

```bash
python scripts/make_icons.py
# -> static/icons/icon-192.png
# -> static/icons/icon-512.png
# -> static/icons/icon-maskable-512.png
```

If Pillow is not installed the committed hand-written
`static/icons/icon.svg` is used instead and the manifest already references it
with `"sizes": "any"`.

> After adding or changing any static asset, run `python manage.py collectstatic`
> locally. Production (Render) runs it automatically, but `runserver` reads the
> local `staticfiles.json` manifest. In development `STATICFILES_MANIFEST_STRICT`
> is relaxed so a stale manifest never crashes the dev server.

## What the service worker caches

| Request | Strategy |
| --- | --- |
| `/offline/`, `/manifest.webmanifest`, core `/static/` assets | Precached on install |
| `GET /static/...` | Stale-while-revalidate (served from cache, refreshed in the background) |
| Page navigations (`mode === 'navigate'`) | **Network only**; falls back to `/offline/` when the network fails |
| Authenticated HTML, `/notifications/…`, JSON/API, downloads, `/media/`, POST/PUT/DELETE | **Never cached** |

The worker only touches same-origin `GET` requests. Cross-origin requests
(Bootstrap/jQuery/Select2 CDNs, OCR provider) are left completely alone.

### Versioning the cache

The cache name is `partner-portal-<CACHE_VERSION>`. Bump the version in
`core/views.py`:

```python
SERVICE_WORKER_CACHE_VERSION = 'v2'
```

On `activate` the worker deletes every cache whose name no longer matches, so a
version bump is enough to invalidate stale assets. Users get the new worker on
their next visit (the browser checks for updates automatically).

## Installing the app

- **Android / Chrome / Edge** — open the site, then use the **Install app**
  item in the top-bar user menu (it only appears once the browser fires
  `beforeinstallprompt`) or Chrome's **⋮ → Install app / Add to Home screen**.
- **iOS / Safari** — open the site, tap **Share**, then **Add to Home Screen**.
  An inline hint appears in the user menu on iOS Safari when the app is not yet
  installed. iOS always uses the `apple-touch-icon` and the
  `apple-mobile-web-app-*` meta tags.

## Testing

### Chrome DevTools

1. **Application → Manifest** — check the name, start URL, colours and that all
   icons load with no warnings.
2. **Application → Service Workers** — confirm `/service-worker.js` is
   *activated and running*, tick **Update on reload** and **Offline**.
3. With **Offline** ticked, navigate to a page: you should see `/offline/`.
4. **Application → Cache Storage** — only `partner-portal-v1` should exist, and
   it should contain only the offline page, manifest and `/static/` assets.

### Lighthouse

Run **Lighthouse → Progressive Web App** on a production build (HTTPS). A PWA
audit needs HTTPS, so test against the Render URL, not `localhost`.

### Manual checklist (do this on a real phone)

- [ ] Install from Chrome on Android; the icon shows the navy "P" mark.
- [ ] On iOS Safari, the *Share → Add to Home Screen* hint is visible.
- [ ] Launching the installed app opens standalone (no browser chrome) at `/`.
- [ ] Turn on airplane mode and open the app: the branded **Retry** page shows.
- [ ] Logged-in pages are **never** served from cache (they require a network).
- [ ] Tables scroll horizontally without scrolling the whole page.
- [ ] Stat cards are 2-up on a tablet and 1-up on a phone.
- [ ] The top-bar search collapses to an icon and expands when tapped.
- [ ] The notification panel fits inside the screen width.
- [ ] Rotate to landscape: no horizontal page scroll, modals stay on screen.
- [ ] On a notch device, the sidebar/offline page respect the home-indicator
      safe area.
