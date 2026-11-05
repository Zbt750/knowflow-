import { h } from 'vue';
import { describe, expect, it, vi } from 'vitest';
import { mountStateComponent, text } from './stateTestHost';
vi.mock('./MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('span',p.text)}}));
import TodayAppendResult from './TodayAppendResult.vue';
import type { TodayAppendResult as Receipt } from '../api/todayAppend';

describe('committed paper receipt', () => {
  it('shows actual item position and stem without inventing absent difficulty', () => {
    const result: Receipt = { operation_id: 'operation', plan_id: 'plan', study_date: '2026-11-04',
      status: 'committed', number_semantics: 'current_position', added_count: 1, total_count: 7,
      items: [{ item_id: 'item', question_id: 'question', question_version_id: 'version', number: 5,
        stem: '已入库版本题干', options: null, kp_id: 'node', kp_name: '洛必达法则',
        question_type: 'single_choice', difficulty: null, source_category: 'development_original',
        question_source: {}, estimated_minutes: 5 }] };
    const wrapper = mountStateComponent(TodayAppendResult, { result });
    try {
      const shown=text(wrapper.root);
      expect(shown).toContain('第 5 题');
      expect(shown).toContain('当前共 7 道');
      expect(shown).toContain('已入库版本题干');
      expect(shown).toContain('洛必达法则');
      expect(shown).not.toContain('基础');
      expect(shown).not.toContain('null');
    } finally { wrapper.unmount(); }
  });
});
