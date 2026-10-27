/* CineVault service worker. The build id below is stamped at build time so each release gets fresh caches. */
const BUILD = '__BUILD__';
const SHELL = `cv-shell-${BUILD}`;
const API = `cv-api-${BUILD}`;
const IMG = 'cv-img-v1';       // posters survive releases
const FONTS = 'cv-fonts-v1';
const PRECACHE = ['/', '/index.html', '/assets/app.js', '/assets/app.css', '/favicon.svg', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png'];
// never touch media or anything that needs Range requests / side effects
const BYPASS = /^\/api\/(stream|download|admin)\/?|\/(links\.txt|playlist\.m3u)$|\/refresh$/;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keep = new Set([SHELL, API, IMG, FONTS]);
    for (const k of await caches.keys()) if (!keep.has(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('message', (e) => { if (e.data === 'SKIP_WAITING') self.skipWaiting(); });

async function trim(name, max) {
  const c = await caches.open(name);
  const keys = await c.keys();
  for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);
}

function withTimeout(promise, ms) {
  return new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('timeout')), ms); promise.then((r) => { clearTimeout(t); res(r); }, (e) => { clearTimeout(t); rej(e); }); });
}

async function networkFirst(req, cacheName, ms, max) {
  const cache = await caches.open(cacheName);
  try {
    const res = await withTimeout(fetch(req), ms);
    if (res.ok) { cache.put(req, res.clone()); if (max) trim(cacheName, max); }
    return res;
  } catch (err) {
    const hit = await cache.match(req);
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidate(req, cacheName, max) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const refresh = fetch(req).then((res) => { if (res.ok || res.type === 'opaque') { cache.put(req, res.clone()); if (max) trim(cacheName, max); } return res; }).catch(() => null);
  return hit || (await refresh) || Response.error();
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || req.headers.has('range')) return;
  const url = new URL(req.url);

  if (url.origin === location.origin) {
    if (BYPASS.test(url.pathname)) return;
    if (req.mode === 'navigate') {
      // app shell: network first so deploys show up, cached shell when offline
      e.respondWith(fetch(req).catch(() => caches.match('/index.html')));
      return;
    }
    if (url.pathname.startsWith('/api/')) { e.respondWith(networkFirst(req, API, 4000, 120)); return; }
    e.respondWith(staleWhileRevalidate(req, SHELL));
    return;
  }
  // cross-origin: posters / cast photos / web fonts
  if (req.destination === 'image') { e.respondWith(staleWhileRevalidate(req, IMG, 300)); return; }
  if (/fonts\.(googleapis|gstatic)\.com$/.test(url.hostname)) { e.respondWith(staleWhileRevalidate(req, FONTS, 30)); }
});
