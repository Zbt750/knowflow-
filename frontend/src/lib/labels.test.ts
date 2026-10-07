import { expect, it } from "vitest";
import { gradeLabel, materialStatusClass, materialStatusLabel, sourceTypeLabel, stateLabel, typeLabel } from "./labels";

it("keeps study labels and skip semantics", () => {
  expect(gradeLabel("skip")).toBe("跳过");
  expect(stateLabel(null)).toBe("汇总节点");
  expect(typeLabel("single_choice")).toBe("选择题");
  expect(typeLabel("future_type")).toBe("future_type");
});
it.each(["pending", "indexing", "ready", "failed"])("maps material status %s", (status) => {
  expect(materialStatusLabel(status)).not.toBe(status);
  expect(materialStatusClass(status)).toBe(`status-${status}`);
});
it("has safe unknown-status fallback and distinct sources", () => {
  expect(materialStatusLabel("unknown")).toBe("unknown");
  expect(materialStatusClass("unknown")).toBe("status-pending");
  expect(sourceTypeLabel("user")).not.toBe(sourceTypeLabel("builtin"));
});
