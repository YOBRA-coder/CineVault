import { useSyncExternalStore } from 'react';

const subs = new Set();
const notify = () => subs.forEach((f) => f());
window.addEventListener('popstate', notify);

export function navigate(to, { replace = false } = {}) {
  const prevPath = location.pathname;
  history[replace ? 'replaceState' : 'pushState']({}, '', to);
  notify();
  if (new URL(to, location.origin).pathname !== prevPath) window.scrollTo(0, 0);
}

const subscribe = (f) => { subs.add(f); return () => subs.delete(f); };
const snapshot = () => location.pathname + location.search;

export function useLocation() {
  const s = useSyncExternalStore(subscribe, snapshot);
  const url = new URL(s, location.origin);
  return { path: url.pathname, params: url.searchParams, key: s };
}

export function setParams(params, current) {
  const next = new URLSearchParams(current);
  Object.entries(params).forEach(([k, v]) => (v === '' || v == null ? next.delete(k) : next.set(k, v)));
  next.delete('page');
  const qs = next.toString();
  navigate(location.pathname + (qs ? '?' + qs : ''), { replace: true });
}

export function Link({ to, children, onClick, ...rest }) {
  return (
    <a
      href={to}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(to);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
