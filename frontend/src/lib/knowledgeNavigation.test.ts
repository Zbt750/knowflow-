import {describe,it,expect} from 'vitest';
import {matchingAncestorIds,knowledgePath,toggleKnowledgeBranch} from './knowledgeNavigation';
import {layoutKnowledgeTree} from './knowledgeTreeLayout';
import type {KnowledgeNodeView} from '../types/practice';
function node(id:string,children:KnowledgeNodeView[]=[]):KnowledgeNodeView{return {id,code:id,name:id,children} as KnowledgeNodeView;}
const tree=[node('数学二',[node('高等数学',[node('微分',[node('长名称曲率知识点')])]),node('线性代数',[node('矩阵')])]),node('408',[node('数据结构',[node('树',[node('二叉树')])])])];
describe('knowledge navigation state',()=>{
  it('starts with no expanded chapter and opens only the requested parent',()=>{
    const initial=new Set<string>();const opened=toggleKnowledgeBranch(initial,'高等数学');
    expect(initial.size).toBe(0);expect([...opened]).toEqual(['高等数学']);expect(opened.has('微分')).toBe(false);
  });
  it('keeps multiple branches independent and preserves descendant manual choice',()=>{
    let opened=new Set(['高等数学','微分','线性代数']);opened=toggleKnowledgeBranch(opened,'高等数学');
    expect([...opened]).toEqual(['微分','线性代数']);expect(toggleKnowledgeBranch(opened,'高等数学').has('微分')).toBe(true);
  });
  it('search expands only complete ancestor paths, no unrelated descendants',()=>{
    expect([...matchingAncestorIds(tree,'曲率')]).toEqual(['数学二','高等数学','微分']);
    expect([...matchingAncestorIds(tree,'高等数学')]).toEqual(['数学二']);
    expect([...matchingAncestorIds(tree,'二叉树')]).toEqual(['408','数据结构','树']);
  });
  it('clearing search does not mutate pre-search expansion or IDs',()=>{
    const before=new Set(['线性代数']);matchingAncestorIds(tree,'曲率');
    expect(matchingAncestorIds(tree,'').size).toBe(0);expect([...before]).toEqual(['线性代数']);
    expect(knowledgePath(tree,'长名称曲率知识点').map(n=>n.id)).toEqual(['数学二','高等数学','微分','长名称曲率知识点']);
    expect(knowledgePath(tree,'missing')).toEqual([]);
  });
  it('canvas branches connect only actual parent-child knowledge nodes from the frog root',()=>{
    const open=new Set(['数学二']);
    const graph=layoutKnowledgeTree(tree,entry=>open.has(entry.id),{},8);
    const ids=graph.nodes.filter(row=>!row.moreFor).map(row=>row.node.id);
    expect(ids).toContain('数学二');
    expect(ids).toContain('高等数学');
    expect(ids).not.toContain('微分');
    expect(graph.edges.find(edge=>edge.key==='root-数学二')?.isRoot).toBe(true);
    expect(graph.edges.find(edge=>edge.key==='高等数学')?.isRoot).toBe(false);
    expect(graph.edges.find(edge=>edge.key==='高等数学')?.targetId).toBe('高等数学');
    expect(graph.edges.every(edge=>graph.nodes.some(row=>row.node.id===edge.targetId))).toBe(true);
  });
});
