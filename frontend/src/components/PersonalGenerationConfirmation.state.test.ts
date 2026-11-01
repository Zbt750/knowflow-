import {expect,it,vi} from 'vitest';
import {mountStateComponent,all,text} from './stateTestHost';
import Card from './PersonalGenerationConfirmation.vue';

it('shows each gradient slot and preserves the selected knowledge identity on explicit confirmation',()=>{
  const confirm=vi.fn();
  const host=mountStateComponent(Card,{busy:false,onConfirm:confirm,confirmation:{question:'生成三道由易到难的练习题',
    message:'确认后生成个人练习',selected_kp_id:'actual-node',question_count:3,difficulty:'basic',
    difficulty_steps:['基础','中等','综合挑战'],nodes:[{kp_id:'actual-node',name:'洛必达法则',code:'k',question_types:['single_choice']}]}});
  try{
    expect(text(host.root)).toContain('基础 → 中等 → 综合挑战');
    expect(text(host.root)).toContain('实际难度仍需核验');
    expect(confirm).not.toHaveBeenCalled();
    const button=all(host.root).find(n=>n.props['data-testid']==='confirm-generation-node')!;
    (button.props.onClick as ()=>void)();
    expect(confirm).toHaveBeenCalledExactlyOnceWith('actual-node');
  }finally{host.unmount();}
});

it('shows explicit allocations for multiple knowledge points and confirms the exact server plan',()=>{
  const confirmTargets=vi.fn();
  const confirmSingle=vi.fn();
  const targets=[
    {kp_id:'lh',name:'洛必达法则',question_type:'single_choice',count:3,difficulty:'basic'},
    {kp_id:'implicit',name:'隐函数求导',question_type:'fill_blank',count:2,difficulty:'improved'},
  ];
  const host=mountStateComponent(Card,{busy:false,onConfirmTargets:confirmTargets,onConfirm:confirmSingle,
    confirmation:{question:'三道洛必达、两道隐函数',message:'已识别分配',selected_kp_id:null,question_count:5,
      difficulty:'basic',proposed_targets:targets,nodes:targets.map(t=>({kp_id:t.kp_id,name:t.name,code:t.kp_id,question_types:['single_choice','fill_blank']}))}});
  try{
    expect(text(host.root)).toContain('洛必达法则：3 道选择题 · 基础');
    expect(text(host.root)).toContain('隐函数求导：2 道填空题 · 中等');
    expect(all(host.root).find(n=>n.props['data-testid']==='generation-node-select')).toBeUndefined();
    expect(confirmTargets).not.toHaveBeenCalled();
    (all(host.root).find(n=>n.props['data-testid']==='confirm-generation-plan')!.props.onClick as()=>void)();
    expect(confirmTargets).toHaveBeenCalledExactlyOnceWith(targets);
    expect(confirmSingle).not.toHaveBeenCalled();
  }finally{host.unmount();}
});
