import type { KnowledgeNodeView } from "../types/practice";

/** Summary groupings are not learning concepts. Promote any real children;
 * retain database IDs and history instead of deleting associated evidence. */
export function learningKnowledgeTree(nodes: KnowledgeNodeView[]): KnowledgeNodeView[] {
  return nodes.flatMap((node) => {
    const children = learningKnowledgeTree(node.children);
    const sourceLabelPlaceholder = node.is_reference_only
      && node.name === "待核对：来源未提供考点标签"
      && (node.practice_eligible_question_count ?? 0) === 0;
    if (node.code.includes(".family.") || node.name.startsWith("专题汇总") || sourceLabelPlaceholder) return children;
    return [{ ...node, children }];
  });
}
