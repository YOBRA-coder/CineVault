import { useEffect, useState, useSyncExternalStore } from 'react';

/* ---------- online / offline ---------- */
export function useOnline() {
  return useSyncExternalStore(
    (cb) => { addEventListener('online', cb); addEventListener('offline', cb); return () => { removeEventListener('online', cb); removeEventListener('offline', cb); }; },
    () => navigator.onLine,
  );
}

/* ---------- install prompt ---------- */
let deferred = null;
const subs = new Set();
const emit = () => subs.forEach((f) => f());
addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; emit(); });
addEventListener('appinstalled', () => { deferred = null; emit(); });

export const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !isStandalone();

export function useInstall() {
  useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => deferred);
  return {
    canInstall: !!deferred && !isStandalone(),
    iosHint: isIOS(),
    install: async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice.catch(() => {});
      deferred = null; emit();
    },
  };
}

/* ---------- service worker + update flow ---------- */
let waiting = null;
export function useUpdate() {
  const [ready, setReady] = useState(!!waiting);
  useEffect(() => { const h = () => setReady(true); addEventListener('cv-update', h); return () => removeEventListener('cv-update', h); }, []);
  return { updateReady: ready, applyUpdate: () => waiting?.postMessage('SKIP_WAITING') };
}

export function registerSW() {
  if (!('serviceWorker' in navigator)) return;
  if (location.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(location.hostname)) return; // SW needs a secure context
  addEventListener('load', async () => {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js');
      const track = (sw) => sw?.addEventListener('statechange', () => {
        if (sw.state === 'installed' && navigator.serviceWorker.controller) { waiting = sw; dispatchEvent(new Event('cv-update')); }
      });
      if (reg.waiting && navigator.serviceWorker.controller) { waiting = reg.waiting; dispatchEvent(new Event('cv-update')); }
      reg.addEventListener('updatefound', () => track(reg.installing));
      setInterval(() => reg.update().catch(() => {}), 60 * 60 * 1000);
      let reloading = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (!reloading) { reloading = true; location.reload(); } });
    } catch { /* offline support is a bonus; the app works without it */ }
  });
}
