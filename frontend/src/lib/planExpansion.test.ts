import { describe, expect, it } from 'vitest';
import { coveredPlanScope, pendingPlanScope } from './planExpansion';

describe('persisted paper coverage versus pending expansion', () => {
  const items = [{ kp_id: 'old', kp_name: '原知识点' }, { kp_id: 'old', kp_name: '原知识点' }];
  it('derives locked coverage from actual items, not selections', () => {
    expect(coveredPlanScope(items)).toEqual([{ id: 'old', name: '原知识点', count: 2 }]);
  });
  it('never offers an existing scope as a pending expansion', () => {
    expect(pendingPlanScope(['old', 'new', 'new'], items)).toEqual(['new']);
    expect(pendingPlanScope([], items)).toEqual([]);
    expect(items).toHaveLength(2);
  });
});
