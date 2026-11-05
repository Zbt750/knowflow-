export type AssistantStatus = 'generating' | 'completed' | 'failed' | 'cancelled';

/** A wire turn has a single terminal outcome. A subsequent history read is
 * authoritative, but contradictory late SSE frames cannot rewrite it locally. */
export function assistantTerminal(current: AssistantStatus, event: string, data: Record<string, unknown>): AssistantStatus {
  if (current !== 'generating') return current;
  if (event === 'error') return 'failed';
  if (event === 'done') return data.status === 'failed' ? 'failed' : data.status === 'cancelled' ? 'cancelled' : 'completed';
  return current;
}
