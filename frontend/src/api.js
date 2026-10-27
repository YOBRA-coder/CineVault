// Anonymous per-device client id: history, list, ratings and downloads are stored server-side against it.
function makeId() {
  return (crypto.randomUUID && crypto.randomUUID()) || 'c' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}
export const CID = (() => {
  try {
    let v = localStorage.getItem('cv_cid');
    if (!v) { v = makeId(); localStorage.setItem('cv_cid', v); }
    return v;
  } catch { return makeId(); }
})();

async function req(path, { method = 'GET', body } = {}) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Client-Id': CID },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  get: (p) => req(p),
  post: (p, body) => req(p, { method: 'POST', body: body ?? {} }),
  put: (p) => req(p, { method: 'PUT' }),
  del: (p) => req(p, { method: 'DELETE' }),
  // keep-alive save used when the tab closes mid-playback
  beacon: (p, body) => fetch('/api' + p, {
    method: 'POST', keepalive: true,
    headers: { 'Content-Type': 'application/json', 'X-Client-Id': CID }, body: JSON.stringify(body),
  }).catch(() => {}),
};

export const streamUrl = (fileId) => `/api/stream/${fileId}?cid=${CID}`;
export const downloadUrl = (fileId) => `/api/download/${fileId}?cid=${CID}`;
export const absolute = (p) => location.origin + p;
