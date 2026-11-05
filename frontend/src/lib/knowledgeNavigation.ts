import type {KnowledgeNodeView} from '../types/practice';

/** 搜索只展开命中的祖先，不把“章节命中”误当作全树展开。 */
export function matchingAncestorIds(nodes:KnowledgeNodeView[],query:string):Set<string>{
  const result=new Set<string>();const term=query.trim().toLocaleLowerCase();
  if(!term)return result;
  const visit=(node:KnowledgeNodeView,path:string[])=>{
    if(`${node.name} ${node.code}`.toLocaleLowerCase().includes(term))path.forEach(id=>result.add(id));
    node.children.forEach(child=>visit(child,[...path,node.id]));
  };
  nodes.forEach(node=>visit(node,[]));return result;
}

export function knowledgePath(nodes:KnowledgeNodeView[],id:string):KnowledgeNodeView[]{
  for(const node of nodes){
    if(node.id===id)return [node];
    const rest=knowledgePath(node.children,id);if(rest.length)return [node,...rest];
  }
  return [];
}

// 纯函数：展开父节点仅影响该节点，关闭再展开保留用户对后代的手动选择。
export function toggleKnowledgeBranch(current:Set<string>,id:string):Set<string>{
  const next=new Set(current);if(next.has(id))next.delete(id);else next.add(id);return next;
}
