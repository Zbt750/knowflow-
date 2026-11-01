import type { KnowledgeNodeView } from "../types/practice";

/** Keep only branches leading to actual online questions. Source references do not count. */
export function practiceTree(nodes: KnowledgeNodeView[], includeUnavailable = false): KnowledgeNodeView[] {
  return nodes.flatMap((node) => {
    const children = practiceTree(Array.isArray(node.children) ? node.children : [], includeUnavailable);
    const availableCount = node.practice_eligible_question_count ?? node.online_question_count;
    const usable = node.is_assessable && (availableCount ?? 0) > 0;
    return children.length || usable || (includeUnavailable && node.is_assessable) ? [{ ...node, children }] : [];
  });
}

export function emptyPracticeInventoryMessage(node: KnowledgeNodeView): string {
  if (node.online_question_count === 0) return '该知识点存在，但目前没有在线题目。可以查看知识讲解或选择其他知识点。';
  if (node.practice_eligible_question_count === 0) return `该知识点存在，有${node.online_question_count ?? '未知数量的'}道在线题目，但当前没有符合可练资格的题；不会把未合格题加入今日卷。`;
  return '当前没有尚未加入今日卷的合格题目。可在“阅览全卷”回看解析，或选择其他知识点。';
}
