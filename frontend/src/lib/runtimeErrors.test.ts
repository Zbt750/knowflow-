import { afterEach, expect, it, vi } from "vitest";
import { clearGlobalFailure, hasGlobalFailure, reportGlobalFailure } from "./runtimeErrors";

afterEach(() => { clearGlobalFailure(); vi.restoreAllMocks(); });
it("sets a recoverable global error flag", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  reportGlobalFailure(new Error("test"), "test component");
  expect(hasGlobalFailure.value).toBe(true);
  clearGlobalFailure();
  expect(hasGlobalFailure.value).toBe(false);
});
