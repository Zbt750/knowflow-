import { describe, expect, it } from "vitest";
import { learningKnowledgeTree } from "./learningKnowledgeTree";
import type { KnowledgeNodeView } from "../types/practice";

describe("knowledge tree presentation", () => {
  it("removes summary groupings, preserves real children and leaves source data untouched", () => {
    const nodes = [{ id: "root", code: "math2", name: "数学二", children: [
      { id: "summary", code: "math2.family.integral", name: "专题汇总：积分", children: [
        { id: "real", code: "math2.integral", name: "定积分", children: [] },
      ] },
      { id: "empty-summary", code: "old.summary", name: "专题汇总：旧专题", children: [] },
      { id: "leaf", code: "math2.limit", name: "极限", children: [] },
    ] }] as unknown as KnowledgeNodeView[];
    expect(learningKnowledgeTree(nodes)[0].children.map(n => n.id)).toEqual(["real", "leaf"]);
    expect(nodes[0].children.map(n => n.id)).toEqual(["summary", "empty-summary", "leaf"]);
  });

  it("excludes empty source-label placeholders without hiding real online learning content", () => {
    const nodes = [
      { id: "placeholder", code: "cs408.os.topic.28afec2a802b", name: "待核对：来源未提供考点标签",
        is_reference_only: true, practice_eligible_question_count: 0, children: [] },
      { id: "online", code: "real.topic", name: "待核对：来源未提供考点标签",
        is_reference_only: true, practice_eligible_question_count: 2, children: [] },
      { id: "concept", code: "real.concept", name: "进程同步", is_reference_only: false,
        practice_eligible_question_count: 0, children: [] },
    ] as unknown as KnowledgeNodeView[];
    expect(learningKnowledgeTree(nodes).map(node => node.id)).toEqual(["online", "concept"]);
    expect(nodes.map(node => node.id)).toEqual(["placeholder", "online", "concept"]);
  });
});
