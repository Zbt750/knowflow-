import { describe, expect, it } from "vitest";
import { practiceTree } from "./practiceTree";
import type { KnowledgeNodeView } from "../types/practice";

describe("练习树", () => {
  it("移除空节点和仅含空节点的章节，保留真实题目的路径", () => {
    const nodes = [{ id: "root", is_assessable: false, children: [
      { id: "empty", is_assessable: true, online_question_count: 0, children: [] },
      { id: "ready", is_assessable: true, online_question_count: 3, children: [] },
      { id: "empty-branch", is_assessable: false, children: [
        { id: "ref", is_assessable: true, is_reference_only: true, online_question_count: 0, children: [] },
      ] },
    ] }] as unknown as KnowledgeNodeView[];
    expect(practiceTree(nodes)[0].children.map(n => n.id)).toEqual(["ready"]);
    expect(nodes[0].children).toHaveLength(3);
  });
  it("以服务端可练题数量为准，原卷标记不隐藏合法题，active或引用数量不冒充可练题", () => {
    const nodes = [
      { id: "eligible-reference", is_assessable: true, is_reference_only: true, practice_eligible_question_count: 2, online_question_count: 2, children: [] },
      { id: "references-only", is_assessable: true, is_reference_only: true, practice_eligible_question_count: 0, online_question_count: 0, children: [] },
      { id: "untrusted-active", is_assessable: true, practice_eligible_question_count: 0, online_question_count: 3, children: [] },
      { id: "unknown", is_assessable: true, children: [] },
    ] as unknown as KnowledgeNodeView[];
    expect(practiceTree(nodes).map(node => node.id)).toEqual(["eligible-reference"]);
  });
});
