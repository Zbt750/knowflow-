import { describe, expect, it } from 'vitest';
import { assistantTerminal } from './assistantTerminal';

describe('one terminal outcome per accepted message', () => {
  it('completed then late error cannot turn the same reply into failure', () => {
    const done = assistantTerminal('generating', 'done', {});
    expect(assistantTerminal(done, 'error', {})).toBe('completed');
  });
  it('an error cannot be overwritten by a contradictory done', () => {
    const failed = assistantTerminal('generating', 'error', {});
    expect(assistantTerminal(failed, 'done', {})).toBe('failed');
  });
  it('failed done remains failure and a fresh turn starts independently', () => {
    expect(assistantTerminal('generating', 'done', {status: 'failed'})).toBe('failed');
    expect(assistantTerminal('generating', 'done', {})).toBe('completed');
  });
});
