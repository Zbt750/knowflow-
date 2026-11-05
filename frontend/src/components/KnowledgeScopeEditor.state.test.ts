import {afterEach,expect,it,vi} from 'vitest';
import {computed,h,reactive} from 'vue';
import type {KnowledgeNodeView} from '../types/practice';
import {knowledgeSelection} from '../lib/knowledgeSelection';
import {practiceTree} from '../lib/practiceTree';
import {mountStateComponent,all,text,flush} from './stateTestHost';
import Editor from './KnowledgeScopeEditor.vue';

let dispose:(()=>void)|undefined;
afterEach(()=>dispose?.());
const leaf=(id:string,name:string,stock=2):KnowledgeNodeView=>({id,code:`synthetic.${id}`,name,is_assessable:true,
 subject:'SYNTHETIC',ordinal:0,is_reference_only:false,summary:null,learning_goal:null,state:null,
 next_review_at:null,mastered_at:null,node_self_grade:null,manual_credit_count:0,effective_confirmation_count:0,
 has_real_variant:false,first_confirmed_on:null,last_confirmed_on:null,day_span:null,gap_items:[],next_step:null,
 required_question_types:{},excluded_question_types:[],required_skill_tags:[],
 practice_eligible_question_count:stock,online_question_count:stock,children:[]});

it('selected names, tree checkboxes and branch counts share one selection, including zero-inventory nodes',async()=>{
 const leaves=[leaf('a','洛必达法则'),leaf('b','矩阵的秩'),leaf('empty','暂无在线题的知识点',0)];
 const tree=practiceTree([{...leaf('root','数学'),is_assessable:false,children:leaves}],true);
 const state=reactive({ids:['a'],search:'',expanded:new Set(['root']),collapsed:new Set<string>()});
 const load=vi.fn();const counts=computed(()=>knowledgeSelection(tree,state.ids).counts);
 const host=mountStateComponent({setup:()=>()=>h(Editor,{nodes:tree,selectedIds:state.ids,
  selectedEntries:state.ids.map(id=>({id,name:leaves.find(n=>n.id===id)!.name})),selectedCounts:counts.value,
  expandedIds:state.expanded,collapsedIds:state.collapsed,search:state.search,loading:false,error:null,onLoad:load,
  'onUpdate:search':(value:string)=>{state.search=value;},onToggle:(id:string)=>{state.ids=state.ids.includes(id)?state.ids.filter(v=>v!==id):[...state.ids,id];},
  onBranch:()=>{state.collapsed=state.collapsed.has('root')?new Set():new Set(['root']);}})},{});
 dispose=host.unmount;await flush();const r=host.root;
 const checkbox=(name:string)=>all(r).find(n=>n.type==='input'&&n.props.type==='checkbox'&&n.props['aria-label']===name)!;
 expect(load).toHaveBeenCalledOnce();expect(text(r)).toContain('当前已选知识点（1）');
 expect(checkbox('洛必达法则').props.checked).toBe(true);
 (checkbox('矩阵的秩').props.onChange as()=>void)();await flush();
 expect(state.ids).toEqual(['a','b']);expect(text(r)).toContain('当前已选知识点（2）');expect(checkbox('矩阵的秩').props.checked).toBe(true);
 const remove=all(r).find(n=>n.props['aria-label']==='移除洛必达法则')!;(remove.props.onClick as()=>void)();await flush();
 expect(state.ids).toEqual(['b']);expect(checkbox('洛必达法则').props.checked).toBe(false);
 (checkbox('暂无在线题的知识点').props.onChange as()=>void)();await flush();
 expect(state.ids).toEqual(['b','empty']);expect(checkbox('暂无在线题的知识点').props.disabled).not.toBe(true);
 const branch=all(r).find(n=>n.props['data-testid']==='scope-branch-synthetic.root')!;
 expect(branch.props['aria-label']).toContain('已选 2');(branch.props.onClick as()=>void)();await flush();
 expect(all(r).some(n=>n.type==='input'&&n.props.type==='checkbox')).toBe(false);
 (branch.props.onClick as()=>void)();await flush();expect(checkbox('矩阵的秩').props.checked).toBe(true);
 const search=all(r).find(n=>n.type==='input'&&n.props.type==='search')!;(search.props.onInput as(e:unknown)=>void)({target:{value:'矩阵'}});await flush();expect(state.search).toBe('矩阵');
 expect(all(r).some(n=>n.props['data-testid']==='scope-editor-tree-scroll')).toBe(true);
 expect(text(r)).not.toContain('确定生成试卷');expect(text(r)).not.toContain('推荐依据');
});


it('three synchronous selection events retain all three leaves and show explicit empty-stock warning',async()=>{
 const nodes=[leaf('a','A'),leaf('b','B'),leaf('c','C',0)];const selected=reactive<string[]>([]);
 const host=mountStateComponent({setup:()=>()=>h(Editor,{nodes,selectedIds:selected,selectedEntries:selected.map(id=>({id,name:id})),selectedCounts:new Map<string,number>(),expandedIds:new Set<string>(),collapsedIds:new Set<string>(),search:'',loading:false,error:null,onToggle:(id:string)=>{const index=selected.indexOf(id);if(index<0)selected.push(id);else selected.splice(index,1);}})},{});dispose=host.unmount;await flush();
 const inputs=all(host.root).filter(n=>n.type==='input'&&n.props.type==='checkbox');expect(inputs).toHaveLength(3);
 for(const input of inputs)(input.props.onChange as()=>void)();await flush();expect([...selected]).toEqual(['a','b','c']);expect(text(host.root)).toContain('当前已选知识点（3）');expect(text(host.root)).toContain('暂无可分配题目');
});
