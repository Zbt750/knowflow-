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
});
