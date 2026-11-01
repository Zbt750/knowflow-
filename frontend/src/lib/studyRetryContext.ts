/** Origin-local pointer only. The server receipt and paper/version binding remain authority. */
const KEY = 'kaoyan.study.retry.v1';
const TTL = 4 * 60 * 60 * 1000;
export function saveStudyRetry(id: string, planId: string, now = Date.now()): void {
  try { localStorage.setItem(KEY, JSON.stringify({id,planId,savedAt:now})); } catch { /* URL still works. */ }
}
export function clearStudyRetry(): void {
  try { localStorage.removeItem(KEY); } catch { /* optional storage */ }
}
export function readStudyRetry(planId: string, now = Date.now()): string | null {
  try {
    const value=JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (value && typeof value.id === 'string' && value.id.length <= 100 && value.planId === planId
      && typeof value.savedAt === 'number' && value.savedAt <= now && now - value.savedAt < TTL) return value.id;
    clearStudyRetry();
  } catch { clearStudyRetry(); }
  return null;
}
