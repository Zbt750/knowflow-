// Notifications invalidate cached views only. The server remains authoritative.
const listeners = new Set<() => void>();
export function notifyPracticeRequestsChanged() { for (const listener of [...listeners]) listener(); }
export function onPracticeRequestsChanged(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
