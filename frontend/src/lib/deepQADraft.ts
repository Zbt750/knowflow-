import type { StudyContext } from "../api/chat";

export interface DeepQADraft {
  sourceSessionId: string | null;
  context: StudyContext;
  problem: string;
  requestKey: string;
  createdAt: number;
}
const prefix = "naifrog-deep-qa-draft:";
const uuid = /^[0-9a-f-]{36}$/i;

/** 只保存浏览器草稿。进入深入问答本身不创建任何服务端会话。 */
export function saveDeepQADraft(sourceSessionId: string | null, context: StudyContext, problem: string): string {
  const id = crypto.randomUUID();
  const draft: DeepQADraft = { sourceSessionId, context, problem: problem.slice(0, 1200), requestKey: id, createdAt: Date.now() };
  sessionStorage.setItem(prefix + id, JSON.stringify(draft));
  return id;
}
export function readDeepQADraft(id: unknown): DeepQADraft | null {
  if (typeof id !== "string" || !uuid.test(id)) return null;
  try {
    const draft = JSON.parse(sessionStorage.getItem(prefix + id) ?? "null") as DeepQADraft | null;
    if (!draft || typeof draft.problem !== "string" || draft.problem.length > 1200
      || !draft.context || !uuid.test(draft.requestKey) || !Number.isFinite(draft.createdAt)
      || Date.now() - draft.createdAt > 2 * 60 * 60 * 1000
      || (draft.sourceSessionId !== null && !uuid.test(draft.sourceSessionId))) return null;
    return draft;
  } catch { return null; }
}
export function removeDeepQADraft(id: string): void { sessionStorage.removeItem(prefix + id); }
