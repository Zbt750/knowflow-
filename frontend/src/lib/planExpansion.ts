type PaperScopeItem = { kp_id: string; kp_name: string };

/** The locked scope is a projection of actual persisted paper items. */
export function coveredPlanScope(items: readonly PaperScopeItem[]) {
  const scopes = new Map<string, { id: string; name: string; count: number }>();
  for (const item of items) {
    const entry = scopes.get(item.kp_id) ?? { id: item.kp_id, name: item.kp_name, count: 0 };
    entry.count += 1;
    scopes.set(item.kp_id, entry);
  }
  return [...scopes.values()];
}

export function pendingPlanScope(ids: readonly string[], items: readonly PaperScopeItem[]) {
  const covered = new Set(items.map(item => item.kp_id));
  return [...new Set(ids)].filter(id => !covered.has(id));
}
