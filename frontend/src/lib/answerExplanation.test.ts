import {expect, it} from 'vitest';
import {answerExplanation} from './answerExplanation';

const proof='## 推导与辨析\n比值判别极限为a；a<1收敛，a>1发散。a=1时调和级数发散，故收敛当且仅当0<a<1。';
const raw='{"boundary_a1": "harmonic_divergent", "interval": "0<a<1", "ratio_limit": "a"}';
it('formats the exact historical screenshot trace without changing proof or answer values',()=>{
  const input=proof+'\n\n## 可复核计算/轨迹\n'+raw;
  const result=answerExplanation(input);
  expect(result.text).toBe(proof);
  expect(result.facts).toEqual([{label:'边界 a=1',value:'调和级数，发散'},{label:'收敛范围',value:'0<a<1'},{label:'比值判别法的极限',value:'a'}]);
  expect(result.raw).toBe(raw);
  expect(input).toContain(raw);
});
it('preserves LaTeX and later prose, accepts fenced multiline records',()=>{
  const math=String.raw`\[\lim_{x\to0}\frac{1-\cos x}{x^2}=\frac12\]`;
  const result=answerExplanation(math+'\n\n## 可复核计算/轨迹\n```json\n{"final_value":"1/2"}\n```\n\n## 注意\n保留条件。');
  expect(result.text).toBe(math+'\n\n## 注意\n保留条件。');
  expect(result.facts).toEqual([{label:'计算结果',value:'1/2'}]);
});
it.each(['原解析：'+raw,'## 可复核计算/轨迹\n不是JSON', '## 可复核计算/轨迹\n[]', '## 可复核计算/轨迹\nnull'])('does not discard or rewrite unrecognized content: %s',text=>{
  expect(answerExplanation(text)).toEqual({text,facts:[],raw:null});
});
it('preserves unknown keys and nested records rather than inventing an interpretation',()=>{
  const result=answerExplanation('## 可复核计算/轨迹\n{"unknown_state":"unconfirmed","steps":[1,2]}');
  expect(result.facts).toEqual([{label:'计算记录（unknown_state）',value:'unconfirmed'},{label:'计算记录（steps）',value:'[1,2]'}]);
});
