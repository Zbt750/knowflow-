import {afterEach, expect, it, vi} from 'vitest';
import {h, reactive} from 'vue';
import {all, flush, mountStateComponent, text} from './stateTestHost';
vi.mock('./MarkdownContent.vue',()=>({default:{props:['text'],setup:(p:{text:string})=>()=>h('article',p.text)}}));
import AnswerExplanation from './AnswerExplanation.vue';
let unmount:(()=>void)|undefined;
afterEach(()=>unmount?.());
it('shows translated trace facts while retaining the exact raw record only in technical details',async()=>{
  const raw='{"boundary_a1":"harmonic_divergent","interval":"0<a<1","ratio_limit":"a"}';
  const mounted=mountStateComponent(AnswerExplanation,{text:'## 推导与辨析\n原始解析条件。\n\n## 可复核计算/轨迹\n'+raw});unmount=mounted.unmount;await flush();
  const facts=all(mounted.root).find(n=>n.type==='dl')!;
  expect(text(facts)).toContain('边界 a=1调和级数，发散');
  expect(text(facts)).toContain('收敛范围0<a<1');
  expect(text(facts)).not.toContain('harmonic_divergent');
  expect(text(all(mounted.root).find(n=>n.type==='pre')!)).toBe(raw);
  expect(all(mounted.root).filter(n=>n.type==='article')).toHaveLength(1);
});
it('switching to a different explanation does not retain the old calculation records',async()=>{
  const props=reactive({text:'旧解析\n\n## 可复核计算/轨迹\n{"interval":"0<a<1"}'});
  const mounted=mountStateComponent({setup:()=>()=>h(AnswerExplanation,props)},{});unmount=mounted.unmount;await flush();
  props.text=String.raw`新解析：\[\frac12\]`;await flush();
  expect(text(mounted.root)).toBe(props.text);
  expect(all(mounted.root).some(n=>n.type==='dl'||n.type==='details')).toBe(false);
});
