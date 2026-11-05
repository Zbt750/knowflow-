import type { KnowledgeNodeView } from "../types/practice";

export function knowledgeSelection(tree: readonly KnowledgeNodeView[], selectedIds: readonly string[]) {
  const selected = new Set(selectedIds);
  const paths = new Map<string, { names: string[]; ancestorIds: string[] }>();
  const counts = new Map<string, number>();
  function visit(node: KnowledgeNodeView, ancestors: KnowledgeNodeView[]): number {
    const children = Array.isArray(node.children) ? node.children : [];
    paths.set(node.id, { names: [...ancestors.map(item => item.name), node.name], ancestorIds: ancestors.map(item => item.id) });
    const count = children.length
      ? children.reduce((sum, child) => sum + visit(child, [...ancestors, node]), 0)
      : Number(node.is_assessable && selected.has(node.id));
    counts.set(node.id, count);
    return count;
  }
  tree.forEach(node => visit(node, []));
  return { paths, counts };
}
