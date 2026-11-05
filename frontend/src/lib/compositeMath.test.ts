import {describe,it,expect} from 'vitest';
import katex from 'katex';
import {markdownWithMath} from './markdownMath';
import {readFileSync,writeFileSync} from 'node:fs';
describe('historical lhopital compact TeX is mathematically preserved',()=>{
  it('preserves EVERY display block in the actual failed response, not just its final fraction',()=>{
    const audit=new URL('../../../storage/quality-audits/naiwa-composite-lhopital-20261021/',import.meta.url);
    const data=JSON.parse(readFileSync(new URL('histories-before.json',audit),'utf8'));
    const messages=Object.values(data).flat() as Array<{message_id:string;content:string}>;
    const raw=messages.find(m=>m.message_id==='d0e3f560-a3e9-410d-bb37-dea56f573014')!.content;
    const html=markdownWithMath(raw);
    writeFileSync(new URL('actual-response-render.html',audit),html);
    expect((html.match(/class="math-block"/g)??[]).length).toBe((raw.match(/\\\[/g)??[]).length);
    expect(html).not.toMatch(/<h[1-6][^>]*>(?:(?!<\/h[1-6]>)[\s\S])*?\\lim/);
  });
  it.each([String.raw`\frac00`,String.raw`\frac12`,String.raw`\frac{\infty}{\infty}`])('retains fraction structure %s',formula=>{
    const html=katex.renderToString(formula,{throwOnError:true});
    expect(html).toContain('<mfrac>');
    if(formula===String.raw`\frac12`)expect(html).toContain('<mn>1</mn><mn>2</mn>');
    expect(markdownWithMath(`\\[\n${formula}\n\\]`)).toContain(formula);
  });
});
