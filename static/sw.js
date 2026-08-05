/*
 * TrackTrack service worker.
 *
 * Served from / rather than /static/, because a worker can only control URLs
 * under its own path - at /static/sw.js it could not see a single page of the
 * app. See the /sw.js route in app.py.
 *
 * The rule that shapes everything here: PAGES ARE NEVER CACHED.
 *
 * Every page in this app is behind a login and full of one business's money.
 * Writing those to disk would mean the numbers survive logging out, stay
 * readable on a shared phone, and come back as current when they are hours
 * stale. So HTML goes to the network, and when the network is gone the user
 * gets an honest offline page instead of yesterday's figures presented as
 * today's.
 *
 * Static assets are the opposite case - public, identical for everyone, and
 * unchanged until the next deploy - so they are served from the cache first.
 * That is what makes the app open instantly on a bad connection, and it is
 * only possible because Stage 2.4a moved them off the CDN: a worker cannot
 * reliably cache another origin's responses.
 *
 * Offline *recording* of sales is Stage 2.4c and is not here yet. This worker
 * makes the app installable and survivable, not yet usable, without a signal.
 */

// Bump to invalidate everything. Old caches are deleted on activate.
const CACHE_VERSION = 'tracktrack-v4';
const OFFLINE_URL = '/offline';

// The shell: enough to render a styled page with icons and no network.
const PRECACHE = [
    OFFLINE_URL,
    '/static/css/style.css',
    '/static/css/combobox.css',
    '/static/js/combobox.js',
    '/static/js/offline-sales.js',
    '/static/css/offline.css',
    '/static/vendor/bootstrap/bootstrap.min.css',
    '/static/vendor/bootstrap/bootstrap.bundle.min.js',
    '/static/vendor/bootstrap-icons/bootstrap-icons.min.css',
    '/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2',
    '/static/logo.png',
    '/static/logo-wordmark.png',
    '/static/icons/icon-192.png',
    '/static/manifest.json',
];

self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE_VERSION);
        // Individually, not addAll: addAll rejects the whole install if any one
        // file 404s, which would leave the user with no worker at all over one
        // renamed asset.
        await Promise.all(PRECACHE.map((url) =>
            cache.add(new Request(url, { cache: 'reload' }))
                 .catch((error) => console.warn('[sw] could not precache', url, error))
        ));
        // Take over immediately rather than waiting for every tab to close.
        // The alternative is a user stuck on a stale worker until they reboot.
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(names
            .filter((name) => name.startsWith('tracktrack-') && name !== CACHE_VERSION)
            .map((name) => caches.delete(name)));
        await self.clients.claim();
    })());
});

function isStaticAsset(url) {
    return url.pathname.startsWith('/static/');
}

self.addEventListener('fetch', (event) => {
    const request = event.request;

    // Anything that changes data goes straight to the network. Replaying a
    // POST from a cache would record a sale twice.
    if (request.method !== 'GET') {
        return;
    }

    const url = new URL(request.url);

    // Only our own origin. A worker cannot see most cross-origin responses
    // anyway, and caching an opaque one wastes quota to no purpose.
    if (url.origin !== self.location.origin) {
        return;
    }

    // The business logo lives in the database and changes when it is replaced,
    // so it is not a static asset even though it looks like one.
    if (isStaticAsset(url)) {
        event.respondWith(cacheFirst(request));
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith(networkOnlyWithOfflinePage(request));
    }
});

/* Static assets: cache first, then network, and remember what came back. */
async function cacheFirst(request) {
    const cached = await caches.match(request, { ignoreSearch: false });
    if (cached) {
        return cached;
    }
    try {
        const response = await fetch(request);
        if (response && response.ok && response.type === 'basic') {
            const cache = await caches.open(CACHE_VERSION);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        // A missing asset offline is a broken image, not a broken app.
        return Response.error();
    }
}

/* Pages: always the network. Never written to the cache - see the file header. */
async function networkOnlyWithOfflinePage(request) {
    try {
        return await fetch(request);
    } catch (error) {
        const offline = await caches.match(OFFLINE_URL);
        return offline || new Response(
            'You are offline.',
            { status: 503, headers: { 'Content-Type': 'text/plain' } }
        );
    }
}
