import { describe, expect, it } from 'vitest';
import { layoutKnowledgeTree } from './knowledgeTreeLayout';
import type { KnowledgeNodeView } from '../types/practice';

function node(id:string,children:KnowledgeNodeView[]=[]):KnowledgeNodeView {
  return {id,code:id,name:id,children,is_assessable:!children.length,is_reference_only:false,state:'unseen'} as KnowledgeNodeView;
}
describe('真实知识树排版',()=>{
  it('空数据有限且不凭空制造节点',()=>{
    const g=layoutKnowledgeTree([],()=>true);expect(g.nodes).toEqual([]);expect(g.edges).toEqual([]);expect(Number.isFinite(g.height)).toBe(true);
  });
  it('大分支按批次展开，不一次塞入全部253个知识点',()=>{
    const root=node('math',Array.from({length:253},(_,i)=>node(`kp-${i}`)));
    const g=layoutKnowledgeTree([root],()=>true);
    expect(g.nodes.filter(n=>!n.moreFor)).toHaveLength(21);
    expect(g.nodes.find(n=>n.moreFor)?.remaining).toBe(233);
    expect(g.nodes.find(n=>n.node.id==='kp-0')?.node).toBe(root.children[0]);
    const more=layoutKnowledgeTree([root],()=>true,{math:40});
    expect(more.nodes.filter(n=>!n.moreFor)).toHaveLength(41);
  });
  it('不改变正式、题源导航、毕业状态等原始语义',()=>{
    const ref=node('reference');ref.is_assessable=false;ref.is_reference_only=true;
    const before=JSON.stringify(ref);const g=layoutKnowledgeTree([node('cs',[ref])],()=>true);
    expect(g.nodes.find(n=>n.key==='reference')?.node).toBe(ref);expect(JSON.stringify(ref)).toBe(before);
  });
  it('关闭分支时不渲染隐藏节点，父子路径和更多控制仍完整',()=>{
    const root=node('root',[node('chapter',[node('leaf')])]);
    const g=layoutKnowledgeTree([root],n=>n.id==='root');
    expect(g.nodes.map(n=>n.key).sort()).toEqual(['chapter','root']);
    expect(g.nodes.find(n=>n.key==='chapter')?.parentId).toBe('root');
    expect(g.edges.map(e=>e.targetId).sort()).toEqual(['chapter','root']);
  });
  it('前三个顶层根节点按三个脚趾分层，子节点沿对应主枝继续展开',()=>{
    const roots=[node('cs408',[node('ds')]),node('math-ii',[node('calculus')]),node('linear-algebra',[node('matrix')])];
    const g=layoutKnowledgeTree(roots,()=>true);
    const [cs,math,linear]=roots.map(root=>g.nodes.find(n=>n.node.id===root.id)!);
    expect(cs.x).toBeLessThan(g.width/2);
    expect(math.x).toBeGreaterThan(g.width/2);
    expect(linear.x).toBeGreaterThan(g.width/2);
    expect(cs.y).toBeCloseTo(g.height/2-300);
    expect(math.y).toBeCloseTo(g.height/2-300);
    expect(linear.y).toBeCloseTo(g.height/2+60);
    expect(g.edges).toHaveLength(6);
    expect(g.edges.filter(edge=>edge.isRoot)).toHaveLength(3);
    expect(g.edges.find(edge=>edge.targetId==='cs408')?.d.startsWith(`M${g.width/2+6} ${g.height/2-190}`)).toBe(true);
    expect(g.edges.find(edge=>edge.targetId==='math-ii')?.d.startsWith(`M${g.width/2+228} ${g.height/2-225}`)).toBe(true);
    expect(g.edges.find(edge=>edge.targetId==='linear-algebra')?.d.startsWith(`M${g.width/2+308} ${g.height/2-46}`)).toBe(true);
    expect(g.edges.every(edge=>Number.isFinite(edge.jointX)&&Number.isFinite(edge.jointY))).toBe(true);
    expect(g.edges.map(edge=>edge.targetId).sort()).toEqual(['calculus','cs408','ds','linear-algebra','math-ii','matrix']);
  });
  it('全部收起时只渲染三个根节点，手机布局中奶蛙和三个根节点同屏',()=>{
    const roots=[node('cs408',[node('ds')]),node('math-ii',[node('calculus')]),node('linear-algebra',[node('matrix')])];
    const desktop=layoutKnowledgeTree(roots,()=>false);
    expect(desktop.nodes.map(row=>row.node.id).sort()).toEqual(['cs408','linear-algebra','math-ii']);
    expect(desktop.edges.filter(edge=>edge.isRoot)).toHaveLength(3);
    const mobile=layoutKnowledgeTree(roots,()=>false,{},8,true,390);
    expect(mobile.nodes).toHaveLength(3);
    expect(Math.max(...mobile.nodes.map(row=>row.y+39))).toBeLessThanOrEqual(520);
    expect(mobile.figureY+430*mobile.figureScale).toBeLessThan(mobile.nodes[0].y-39);
  });
  it('深层两学科无越界、同列标签不重叠且坐标稳定',()=>{
    const roots=['math','cs'].map(s=>node(s,Array.from({length:8},(_,i)=>node(`${s}.${i}`,Array.from({length:5},(_,j)=>node(`${s}.${i}.${j}`))))));
    const g=layoutKnowledgeTree(roots,()=>true);
    for(const n of g.nodes){expect(n.x-105).toBeGreaterThanOrEqual(0);expect(n.x+105).toBeLessThanOrEqual(g.width);expect(n.y).toBeGreaterThan(0);expect(n.y).toBeLessThan(g.height)}
    for(const n of g.nodes)for(const other of g.nodes){if(other.key!==n.key&&other.x===n.x)expect(Math.abs(other.y-n.y)).toBeGreaterThanOrEqual(78)}
    expect(layoutKnowledgeTree(roots,()=>true)).toEqual(g);
  });
});
