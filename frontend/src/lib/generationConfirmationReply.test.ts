import {expect,it} from 'vitest';
import {resolveGenerationConfirmationReply} from './generationConfirmationReply';

const targets=[
  {kp_id:'lh',name:'洛必达法则',question_type:'single_choice',count:3,difficulty:'basic'},
  {kp_id:'implicit',name:'隐函数求导',question_type:'fill_blank',count:2,difficulty:'improved'},
];

it('a short acceptance applies the full pending multi-node allocation, never just one node',()=>{
  const result=resolveGenerationConfirmationReply('好的',{question:'多知识点出题',message:'已识别',selected_kp_id:null,
    question_count:5,difficulty:'basic',nodes:targets.map(t=>({kp_id:t.kp_id,name:t.name,code:t.kp_id,question_types:[]})),
    proposed_targets:targets});
  expect(result).toEqual({kind:'confirm-targets',targets});
});

it.each(['我确定','我确认','好的','接受此方案'])(
  'spoken acceptance "%s" applies the exact pending multi-node allocation', (reply)=>{
    const result=resolveGenerationConfirmationReply(reply,{question:'多知识点出题',message:'已识别',selected_kp_id:null,
      question_count:5,difficulty:'basic',nodes:targets.map(t=>({kp_id:t.kp_id,name:t.name,code:t.kp_id,question_types:[]})),
      proposed_targets:targets});
    expect(result).toEqual({kind:'confirm-targets',targets});
  });

it('a partial knowledge-point mention cannot silently accept only part of the pending allocation',()=>{
  const result=resolveGenerationConfirmationReply('确定 洛必达法则',{question:'多知识点出题',message:'已识别',selected_kp_id:null,
    question_count:5,difficulty:'basic',nodes:targets.map(t=>({kp_id:t.kp_id,name:t.name,code:t.kp_id,question_types:[]})),
    proposed_targets:targets});
  expect(result).toEqual({kind:'needs-node'});
});
