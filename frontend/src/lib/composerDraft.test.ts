import { describe, expect, it } from "vitest";
import { restoreComposerDraft, takeComposerDraft } from "./composerDraft";

describe("learning assistant composer draft", () => {
  it("takes a trimmed message and clears the field immediately", () => {
    expect(takeComposerDraft("  复习极限  ")).toEqual({ submitted: "复习极限", remainder: "" });
  });

  it("restores a failed message when no newer draft exists", () => {
    expect(restoreComposerDraft("", "复习极限")).toBe("复习极限");
  });

  it("does not overwrite a newer draft while restoring a failure", () => {
    expect(restoreComposerDraft("再看一下导数", "复习极限")).toBe("再看一下导数");
  });
});
