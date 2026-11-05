/** Keep the submitted message separate from the editable composer value. */
export function takeComposerDraft(value: string) {
  return { submitted: value.trim(), remainder: "" };
}

/** Restore a failed submission only when the user has not started another draft. */
export function restoreComposerDraft(currentDraft: string, submitted: string) {
  return currentDraft.trim() ? currentDraft : submitted;
}
