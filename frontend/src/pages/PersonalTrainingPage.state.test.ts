import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PersonalTrainingQuestion } from "../api/personalTrainings";
import { all, flush, mountStateComponent, text } from "../components/stateTestHost";

const mocks = vi.hoisted(() => ({
  createSession: vi.fn(), knowledge: vi.fn(), list: vi.fn(), read: vi.fn(), report: vi.fn(),
  create: vi.fn(), append: vi.fn(), transition: vi.fn(), answer: vi.fn(), next: vi.fn(),
  saveDraft: vi.fn(),
}));
vi.mock("../api/chat", () => ({ createChatSession: mocks.createSession }));
vi.mock("../api/study", () => ({ fetchKnowledgeTree: mocks.knowledge }));
vi.mock("../api/personalTrainings", () => ({
  createPersonalTraining: mocks.create, appendPersonalTraining: mocks.append,
  createNextPersonalTraining: mocks.next, listPersonalTrainings: mocks.list,
  readPersonalTraining: mocks.read, readPersonalTrainingReport: mocks.report,
  transitionPersonalTraining: mocks.transition, answerPersonalTrainingItem: mocks.answer,
  savePersonalTrainingDraft: mocks.saveDraft,
}));
vi.mock("vue-router", () => ({ useRoute: () => ({ query: {} }) }));
import PersonalTrainingPage from "./PersonalTrainingPage.vue";

let view: ReturnType<typeof mountStateComponent>;
const row = (id: string, title: string, items: PersonalTrainingQuestion[] = []) => ({
  training_id: id, owner_session_id: "study-owner", request_key: `${id}-request`, title,
  status: "paused" as const, version: 3, knowledge_point_ids: ["kp-1"], selection_basis: "selected",
  requested_count: 2, target_minutes: 30, actual_minutes: 10, inventory_shortfall: 0,
  minutes_shortfall: 20, item_count: 2, completed_count: 1, remaining_count: 1, progress_percent: 50,
  started_at: "2026-10-29T00:00:00+00:00", paused_at: "2026-10-29T00:10:00+00:00",
  finished_at: null, adapted_from_training_id: null, items,
});

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key: string) => key === "kaoyan.personal-training.owner-session.v1"
      ? "study-owner" : key === "kaoyan.personal-training.selected.v1" ? "training-2" : null),
    setItem: vi.fn(), removeItem: vi.fn(),
  });
  mocks.knowledge.mockResolvedValue({ nodes: [] });
  mocks.list.mockResolvedValue([row("training-1", "较早的专项"), row("training-2", "昨日未完成专项")]);
  mocks.createSession.mockResolvedValue({ session_id: "new-study-owner" });
});

afterEach(() => { view?.unmount(); vi.unstubAllGlobals(); vi.resetAllMocks(); });

it("refresh restores the previously selected persisted training without writing chat messages", async () => {
  view = mountStateComponent(PersonalTrainingPage, {});
  await flush();
  expect(text(view.root)).toContain("昨日未完成专项");
  const selector = all(view.root).find((node) => node.type === "select" && node.props["aria-label"] === "选择专项训练");
  expect(selector).toBeDefined();
  expect(mocks.list).toHaveBeenCalledWith("study-owner");
  expect(localStorage.setItem).toHaveBeenCalledWith("kaoyan.personal-training.selected.v1", "training-2");
  expect(mocks.createSession).not.toHaveBeenCalled();
  expect(mocks.create).not.toHaveBeenCalled();
  expect(mocks.append).not.toHaveBeenCalled();
  expect(mocks.answer).not.toHaveBeenCalled();
});

it("creates only an owner study session when none is saved and does not send a chat turn", async () => {
  vi.stubGlobal("localStorage", { getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn() });
  mocks.list.mockResolvedValue([]);
  view = mountStateComponent(PersonalTrainingPage, {});
  await flush();
  expect(mocks.createSession).toHaveBeenCalledWith("个人专项训练空间", "builtin", { purpose: "study" });
  expect(mocks.list).toHaveBeenCalledWith("new-study-owner");
  expect(mocks.create).not.toHaveBeenCalled();
});

it("restores a saved unsubmitted answer from the independent training API after refresh", async () => {
  const item = { item_id: "item-1", ordinal: 1, question_id: "question-1", question_version_id: "version-1",
    kp_id: "kp-1", question_type: "calculation", difficulty: "basic", estimated_minutes: 5,
    stem: "TEST_FIXTURE: 求导。", options: null, completed: false, completed_at: null,
    latest_result: null, draft_answer: "TEST_FIXTURE: 这是尚未提交的草稿", draft_selected_option: null,
    draft_revision: 2, draft_saved_at: "2026-10-30T00:00:00+00:00" };
  mocks.list.mockResolvedValue([row("training-2", "昨日未完成专项", [item])]);
  view = mountStateComponent(PersonalTrainingPage, {});
  await flush();
  const answer = all(view.root).find((node) => node.type === "textarea");
  expect(answer?.value).toBe("TEST_FIXTURE: 这是尚未提交的草稿");
  expect(mocks.answer).not.toHaveBeenCalled();
  expect(mocks.saveDraft).not.toHaveBeenCalled();
});
