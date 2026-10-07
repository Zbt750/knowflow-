import type { KnowledgeNodeView } from "../types/practice";

/** Keep only branches leading to actual online questions. Source references do not count. */
export function practiceTree(nodes: KnowledgeNodeView[]): KnowledgeNodeView[] {
  return nodes.flatMap((node) => {
    const children = practiceTree(Array.isArray(node.children) ? node.children : []);
    const availableCount = node.practice_eligible_question_count ?? node.online_question_count;
    const usable = node.is_assessable && (availableCount ?? 0) > 0;
    return children.length || usable ? [{ ...node, children }] : [];
  });
}
