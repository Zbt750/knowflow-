import { describe, expect, it } from "vitest";
import type { KnowledgeNodeView } from "../types/practice";
import { knowledgeSelection } from "./knowledgeSelection";

const node = (id: string, name: string, children: KnowledgeNodeView[] = []) => ({ id, code: id, name, is_assessable: children.length === 0, children } as KnowledgeNodeView);
const tree = [node("math", "数学", [node("calculus", "高等数学", [node("limit", "极限"), node("derivative", "导数")])]), node("english", "英语", [node("word", "词汇")])];

describe("selected knowledge paths", () => {
  it("keeps all ancestors and the root name", () => {
    const result = knowledgeSelection(tree, ["limit"]);
    expect(result.paths.get("limit")).toEqual({ names: ["数学", "高等数学", "极限"], ancestorIds: ["math", "calculus"] });
  });
  it("counts each root independently even when the visible tree is filtered", () => {
    const result = knowledgeSelection(tree, ["limit", "derivative", "word"]);
    expect(result.counts.get("math")).toBe(2);
    expect(result.counts.get("calculus")).toBe(2);
    expect(result.counts.get("english")).toBe(1);
  });
  it("removing the last leaf clears ancestor counts without inventing missing paths", () => {
    const result = knowledgeSelection(tree, ["word", "unknown"]);
    expect(result.counts.get("math")).toBe(0);
    expect(result.counts.get("english")).toBe(1);
    expect(result.paths.has("unknown")).toBe(false);
  });
});
