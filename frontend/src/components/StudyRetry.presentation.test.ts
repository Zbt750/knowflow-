import {afterEach, expect, it, vi} from 'vitest';
import {h} from 'vue';
import {all,mountStateComponent,text} from './stateTestHost';
vi.mock('./MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('article',p.text)}}));
import StudyFocus from './StudyFocus.vue';
import Picker from './KnowledgeQuestionPickerTree.vue';
const cleanups:Array<()=>void>=[];afterEach(()=>cleanups.splice(0).forEach(fn=>fn()));
it.each([['',true],['Z',true],['B',false]] as const)('single choice option %s enables submit only when valid', (selectedOption,disabled)=>{
 const view=mountStateComponent(StudyFocus,{item:{id:'i',question_type:'single_choice',options:{A:'甲',B:'乙'},stem:'题干',skill_tags:[],completed:false},selectedOption,hasPrevious:false,hasNext:false,displayNumber:1});cleanups.push(view.unmount);
 const submit=()=>all(view.root).find(n=>n.props['data-testid']==='submit-answer')!;
 expect(submit().props.disabled).toBe(disabled);
});
it.each(['短题干','长题干'.repeat(400)])('navigation precedes question content without an overlay: %s',stem=>{
 const view=mountStateComponent(StudyFocus,{item:{id:'i',stem,kp_name:'测试',skill_tags:[],completed:false},hasPrevious:true,hasNext:true,displayNumber:1});cleanups.push(view.unmount);
 const nodes=all(view.root);expect(nodes.indexOf(nodes.find(n=>n.props['data-testid']==='previous-question')!)).toBeLessThan(nodes.indexOf(nodes.find(n=>n.props['data-testid']==='focus-stem')!));
 expect(nodes.filter(n=>n.props['data-testid']==='previous-question')).toHaveLength(1);
 expect(nodes.filter(n=>n.props['data-testid']==='retry-practice')).toHaveLength(0);
});
it.each([{questions:[]},{questions:[{id:'q',stem:'合成题',is_variant:false}]}])('empty inventory offers honest alternatives; stocked inventory shows actual candidates',({questions})=>{
 const view=mountStateComponent(Picker,{nodes:[{id:'k',name:'合成节点',is_assessable:true,children:[]}],expandedIds:new Set(['k']),collapsedIds:new Set(),questions:{k:questions},questionLoadingIds:new Set(),selectedQuestionIds:[],autoExpandBranches:true,level:0});cleanups.push(view.unmount);
 if(questions.length)expect(text(view.root)).toContain('合成题');else {expect(text(view.root)).toContain('没有尚未加入今日卷的合格题目');expect(text(view.root)).not.toContain('答题卡');expect(all(view.root).some(n=>n.props['data-testid']==='empty-return-paper')).toBe(true);}
});
it.each([false,true])('empty-stock buttons emit real navigation actions, wrong-entry availability=%s',hasWrong=>{
 const actions:string[]=[];
 const view=mountStateComponent(Picker,{nodes:[{id:'k',name:'节点',is_assessable:true,children:[]}],expandedIds:new Set(['k']),collapsedIds:new Set(),questions:{k:[]},questionLoadingIds:new Set(),selectedQuestionIds:[],autoExpandBranches:true,level:1,wrongKpIds:new Set(hasWrong?['k']:[]),onReturnPaper:()=>actions.push('paper'),onReviewWrong:(id:string)=>actions.push(id),onChooseOther:()=>actions.push('other')});cleanups.push(view.unmount);
 const button=(id:string)=>all(view.root).find(n=>n.props['data-testid']===id);
 (button('empty-return-paper')!.props.onClick as ()=>void)();(button('empty-choose-other')!.props.onClick as ()=>void)();
 expect(actions).toEqual(['paper','other']);
 expect(Boolean(button('empty-review-wrong'))).toBe(hasWrong);
 if(hasWrong){(button('empty-review-wrong')!.props.onClick as ()=>void)();expect(actions).toContain('k');}
});
it('a standalone wrong retry keeps its result but offers no nested-creation button',()=>{
 const view=mountStateComponent(StudyFocus,{item:{id:'retry',retry_source_id:'root',stem:'题干',skill_tags:[],completed:true,answer_submission:{result:'wrong'}},standalone:true,hasPrevious:false,hasNext:false,displayNumber:0});cleanups.push(view.unmount);
 expect(all(view.root).some(n=>n.props['data-testid']==='retry-practice')).toBe(false);
 expect(text(view.root)).toContain('不再创建下一层重练');expect(text(view.root)).toContain('答案错误');
});
