/*
 * Recording sales without a signal.
 *
 * The sale form posts normally when there is a network. When there is not, the
 * sale goes into IndexedDB and is sent when the connection returns.
 *
 * Design rules, each of them about not losing or inventing money:
 *
 * - A queued sale is NEVER deleted until the server has confirmed it. Not on
 *   error, not on a bad response, not on a failed parse. The only thing that
 *   removes a sale from this queue is the server saying it recorded it.
 * - Every sale carries an id generated here, before it is ever sent. A sync
 *   that times out after the server committed looks identical to one that
 *   failed, so retrying is normal - and without that id, a retry sells the
 *   same crate twice.
 * - The device never decides anything. It caches prices to show the user a
 *   number, but the server re-resolves price and stock at sync time. A cached
 *   price is a guess about the past.
 * - Pending is stated loudly. A sale sitting in this queue is not in the books
 *   yet, and the one thing worse than a sale that has not synced is a sale the
 *   user believes has.
 */
(function (window, document) {
    'use strict';

    const DB_NAME = 'tracktrack';
    const DB_VERSION = 1;
    const STORE_QUEUE = 'queued_sales';
    const STORE_CATALOGUE = 'catalogue';
    const MAX_BATCH = 50;

    let dbPromise = null;

    function openDb() {
        if (dbPromise) {
            return dbPromise;
        }
        dbPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(STORE_QUEUE)) {
                    db.createObjectStore(STORE_QUEUE, { keyPath: 'client_id' });
                }
                if (!db.objectStoreNames.contains(STORE_CATALOGUE)) {
                    db.createObjectStore(STORE_CATALOGUE, { keyPath: 'key' });
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
        return dbPromise;
    }

    function tx(store, mode, work) {
        return openDb().then((db) => new Promise((resolve, reject) => {
            const transaction = db.transaction(store, mode);
            const result = work(transaction.objectStore(store));
            transaction.oncomplete = () => resolve(result && result.result);
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(transaction.error);
        }));
    }

    function readAll(store) {
        return openDb().then((db) => new Promise((resolve, reject) => {
            const request = db.transaction(store, 'readonly').objectStore(store).getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        }));
    }

    /* crypto.randomUUID is unavailable on http:// origins and older WebViews,
       so there is a fallback - an id is required, not optional. */
    function newId() {
        if (window.crypto && window.crypto.randomUUID) {
            return window.crypto.randomUUID();
        }
        return 'sale-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10);
    }

    const Offline = {
        /* --- the catalogue ------------------------------------------------ */

        async refreshCatalogue() {
            const response = await fetch('/api/v1/catalogue', { credentials: 'same-origin' });
            if (!response.ok) {
                return null;                     // logged out, or not on this plan
            }
            const data = await response.json();
            await tx(STORE_CATALOGUE, 'readwrite', (store) =>
                store.put({ key: 'current', data: data, cached_at: Date.now() }));
            return data;
        },

        async catalogue() {
            const row = await tx(STORE_CATALOGUE, 'readonly', (store) => store.get('current'));
            return row ? row.data : null;
        },

        /* --- the queue ----------------------------------------------------- */

        async queue(sale) {
            sale.client_id = sale.client_id || newId();
            sale.recorded_at = new Date().toISOString();
            sale.state = 'pending';
            await tx(STORE_QUEUE, 'readwrite', (store) => store.put(sale));
            Offline.announce();
            return sale.client_id;
        },

        pending() {
            return readAll(STORE_QUEUE);
        },

        async remove(clientId) {
            await tx(STORE_QUEUE, 'readwrite', (store) => store.delete(clientId));
        },

        async markConflict(clientId, message) {
            const sale = await tx(STORE_QUEUE, 'readonly', (store) => store.get(clientId));
            if (!sale) {
                return;
            }
            // Kept, not discarded. The user has to see this and decide.
            sale.state = 'conflict';
            sale.conflict = message;
            await tx(STORE_QUEUE, 'readwrite', (store) => store.put(sale));
        },

        /* --- syncing ------------------------------------------------------- */

        async sync() {
            if (!navigator.onLine) {
                return { skipped: 'offline' };
            }
            const all = await Offline.pending();
            const sendable = all.filter((s) => s.state === 'pending').slice(0, MAX_BATCH);
            if (!sendable.length) {
                return { sent: 0 };
            }

            // A fresh token: CSRF tokens expire after an hour, and a sale queued
            // at dawn syncs on whatever token this page was rendered with.
            let token;
            try {
                const session = await fetch('/api/v1/session', { credentials: 'same-origin' });
                if (!session.ok) {
                    return { error: 'signed-out' };
                }
                token = (await session.json()).csrf_token;
            } catch (error) {
                return { error: 'unreachable' };
            }

            let body;
            try {
                const response = await fetch('/api/v1/sales', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
                    body: JSON.stringify({ sales: sendable }),
                });
                if (!response.ok) {
                    // Nothing is removed. Whatever went wrong, these sales are
                    // still the only copy that exists.
                    return { error: 'rejected', status: response.status };
                }
                body = await response.json();
            } catch (error) {
                return { error: 'unreachable' };
            }

            let accepted = 0;
            let conflicts = 0;
            for (const result of body.results || []) {
                if (result.status === 'accepted') {
                    await Offline.remove(result.client_id);
                    accepted += 1;
                } else if (result.status === 'conflict' || result.status === 'rejected') {
                    await Offline.markConflict(result.client_id, result.message);
                    conflicts += 1;
                }
                // 'retry' is left exactly as it is, to go again next time.
            }
            Offline.announce();
            return { accepted, conflicts };
        },

        /* --- telling the user ---------------------------------------------- */

        async announce() {
            const all = await Offline.pending();
            const pending = all.filter((s) => s.state === 'pending').length;
            const conflicts = all.filter((s) => s.state === 'conflict').length;
            document.dispatchEvent(new CustomEvent('tracktrack:queue', {
                detail: { pending, conflicts, sales: all },
            }));
            Offline.paintBadge(pending, conflicts);
        },

        paintBadge(pending, conflicts) {
            let badge = document.getElementById('offline-queue-badge');
            if (!pending && !conflicts) {
                if (badge) { badge.remove(); }
                return;
            }
            if (!badge) {
                badge = document.createElement('div');
                badge.id = 'offline-queue-badge';
                badge.className = 'offline-queue-badge';
                document.body.appendChild(badge);
            }
            badge.className = 'offline-queue-badge' + (conflicts ? ' has-conflict' : '');
            const parts = [];
            if (pending) {
                parts.push('<i class="bi bi-cloud-arrow-up me-1"></i>' +
                           pending + (pending === 1 ? ' sale waiting to sync' : ' sales waiting to sync'));
            }
            if (conflicts) {
                parts.push('<i class="bi bi-exclamation-triangle-fill me-1"></i>' +
                           conflicts + ' need attention');
            }
            badge.innerHTML = parts.join('<br>');
            badge.title = 'Recorded on this device and not yet in your records.';
        },
    };

    window.TrackTrackOffline = Offline;

    document.addEventListener('DOMContentLoaded', () => {
        Offline.announce();
        if (navigator.onLine) {
            Offline.refreshCatalogue().catch(() => {});
            Offline.sync().catch(() => {});
        }
    });

    // The moment a signal returns, empty the queue. A wholesaler should never
    // have to remember to press anything.
    window.addEventListener('online', () => {
        Offline.sync().catch(() => {});
        Offline.refreshCatalogue().catch(() => {});
    });
})(window, document);
