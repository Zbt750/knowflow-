import {expect,it} from 'vitest';
import {practiceTree,emptyPracticeInventoryMessage} from './practiceTree';
import {resolveGenerationConfirmationReply} from './generationConfirmationReply';
import type {KnowledgeNodeView} from '../types/practice';
import type {GenerationConfirmation} from '../api/personalQuestions';
import {readFileSync} from 'node:fs';

it('the single primary generation control precedes long recommendation and configuration content',()=>{
  // Source structure only: viewport geometry remains an independent UI check.
  const source=readFileSync(new URL('../pages/StudyPage.vue',import.meta.url),'utf8');
  expect(source.match(/<button\b[^>]*data-testid="generate-plan"/g)).toHaveLength(1);
  expect(source.indexOf('data-testid="generate-plan"')).toBeLessThan(source.indexOf('class="study-setup-grid"'));
});

it('the picker can retain existing nodes whose inventory is not eligible',()=>{
  const nodes=[{id:'geometric',name:'等比级数',is_assessable:true,children:[],online_question_count:1,practice_eligible_question_count:0}] as unknown as KnowledgeNodeView[];
  expect(practiceTree(nodes, true).map(n=>n.id)).toEqual(['geometric']);
  expect(practiceTree(nodes)).toEqual([]); // Existing selection callers keep their eligibility contract.
});
it('unmatched textual confirmation is visibly different from no selection',()=>{
  const card={nodes:[{kp_id:'k',name:'等比级数',code:'series.geometric'}],selected_kp_id:'k'} as GenerationConfirmation;
  expect(resolveGenerationConfirmationReply('确定 等价无穷小替换',card)).toEqual({kind:'unmatched-node',requested:'等价无穷小替换'});
  expect(resolveGenerationConfirmationReply('确定 等比级数',card)).toEqual({kind:'confirm',kpId:'k'});
});
it.each([[0,0,'没有在线题目'],[1,0,'不符合'],[2,2,'尚未加入']] as const)('existing node inventory states online=%s eligible=%s', (online,eligible,phrase)=>{
 const result=emptyPracticeInventoryMessage({online_question_count:online,practice_eligible_question_count:eligible} as KnowledgeNodeView);
 expect(result).toContain(phrase==='不符合'?'没有符合可练资格':phrase);expect(result).not.toContain('没有找到匹配的知识点');
});
