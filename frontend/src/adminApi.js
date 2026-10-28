import { CID } from './api.js';

export const tokenKey = 'cv_admin';
export const getToken = () => { try { return sessionStorage.getItem(tokenKey) || ''; } catch { return ''; } };

export async function adm(method, path, body) {
  const r = await fetch('/api/admin' + path, {
    method, headers: { 'Content-Type': 'application/json', 'X-Client-Id': CID, 'X-Admin-Token': getToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; throw e; }
  return data;
}

// YouTube watch/short links can be played inside the app; everything else opens in a new tab.
export function youtubeId(url) {
  const m = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/)|youtu\.be\/)([\w-]{11})/.exec(url || '');
  return m ? m[1] : null;
}
