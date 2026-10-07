import type { KnowledgeNodeView } from "../types/practice";

/** Summary groupings are not learning concepts. Promote any real children;
 * retain database IDs and history instead of deleting associated evidence. */
export function learningKnowledgeTree(nodes: KnowledgeNodeView[]): KnowledgeNodeView[] {
  return nodes.flatMap((node) => {
    const children = learningKnowledgeTree(node.children);
    if (node.code.includes(".family.") || node.name.startsWith("专题汇总")) return children;
    return [{ ...node, children }];
  });
}
