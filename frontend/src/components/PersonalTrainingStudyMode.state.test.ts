import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { h, reactive } from "vue";
import { all, deferred, flush, mountStateComponent, text } from "./stateTestHost";
import type { PersonalTrainingReport, PersonalTrainingView } from "../api/personalTrainings";

const mocks = vi.hoisted(() => ({
  read: vi.fn(), report: vi.fn(), saveDraft: vi.fn(), answer: vi.fn(), transition: vi.fn(), tree: vi.fn(),
}));
vi.mock("../api/personalTrainings", () => ({
  readPersonalTraining: mocks.read,
  readPersonalTrainingReport: mocks.report,
  savePersonalTrainingDraft: mocks.saveDraft,
  answerPersonalTrainingItem: mocks.answer,
  transitionPersonalTraining: mocks.transition,
}));
vi.mock("../api/study", () => ({ fetchKnowledgeTree: mocks.tree }));
vi.mock("./MarkdownContent.vue", () => ({ default: { props: ["text"], setup: (props: { text: string }) => () => h("span", {}, props.text) } }));
vi.mock("./StudyFocus.vue", () => ({
  default: {
    props: ["item", "readOnly", "rawAnswer", "selectedOption", "notice", "hasPrevious", "hasNext"],
    emits: ["submit-answer", "continue", "previous", "update:rawAnswer", "update:selectedOption"],
    setup(props: Record<string, unknown>, { emit }: { emit: (name: string, ...args: unknown[]) => void }) {
      return () => h("div", { "data-testid": "focus-stub", "data-read-only": String(props.readOnly) }, [
        h("span", { "data-testid": "focus-stem" }, String((props.item as { stem?: string } | null)?.stem ?? "")),
        h("span", { "data-testid": "focus-notice" }, String(props.notice ?? "")),
        h("textarea", { "data-testid": "focus-answer", value: props.rawAnswer, onInput: (event: Event) => emit("update:rawAnswer", (event.target as HTMLTextAreaElement).value) }),
        h("button", { "data-testid": "focus-submit", onClick: () => emit("submit-answer") }, "提交"),
      ]);
    },
  },
}));
import PersonalTrainingStudyMode from "./PersonalTrainingStudyMode.vue";

const owner = "11111111-1111-4111-8111-111111111111";
const trainingId = "22222222-2222-4222-8222-222222222222";
function training(overrides: Partial<PersonalTrainingView> = {}): PersonalTrainingView {
  return {
    training_id: trainingId, owner_session_id: owner, request_key: "req", title: "洛必达专项", status: "active", version: 1,
    knowledge_point_ids: ["kp"], selection_basis: "selected", requested_count: 1, target_minutes: 30, actual_minutes: 5,
    inventory_shortfall: 0, minutes_shortfall: 0, item_count: 1, completed_count: 0, remaining_count: 1,
    progress_percent: 0, started_at: "2026-10-30T00:00:00Z", paused_at: null, finished_at: null,
    adapted_from_training_id: null, items: [{ item_id: "item", ordinal: 1, question_id: "question", question_version_id: "version",
      kp_id: "kp", question_type: "calculation", difficulty: "basic", estimated_minutes: 5, stem: "求极限", options: null,
      completed: false, draft_answer: "已暂存答案", draft_selected_option: null, draft_revision: 2,
      draft_saved_at: "2026-10-30T00:01:00Z", completed_at: null, latest_result: null }],
    ...overrides,
  };
}
let unmount: (() => void) | undefined;
beforeEach(() => {
  // The in-memory Vue renderer runs in Vitest's node environment. This
  // component uses only window timers, so expose the equivalent global timers
  // without installing a DOM or changing the production component behavior.
  vi.stubGlobal("window", globalThis);
  mocks.read.mockResolvedValue(training()); mocks.tree.mockResolvedValue({ nodes: [{ id: "kp", name: "洛必达法则", children: [] }] });
  mocks.report.mockResolvedValue({ training_id: trainingId, status: "completed", question_count: 1, submitted_count: 1,
    right_count: 1, wrong_count: 0, unknown_count: 0, wrong_knowledge_points: [], next_round_recommendation: null, evidence_scope: "personal_training" });
  mocks.saveDraft.mockImplementation(async (_id: string, _item: string, body: { draft_answer: string | null; expected_draft_revision: number }) => {
    const value = training(); value.items[0].draft_answer = body.draft_answer; value.items[0].draft_revision = body.expected_draft_revision + 1; return value;
  });
  mocks.answer.mockImplementation(async () => { const value = training({ version: 2, completed_count: 1, remaining_count: 0, progress_percent: 100 }); value.items[0].completed = true; value.items[0].latest_result = "right"; return value; });
  mocks.transition.mockImplementation(async (_id: string, action: string) => training({ status: action === "pause" ? "paused" : "active", version: 2, paused_at: action === "pause" ? "2026-10-30T00:02:00Z" : null }));
});
afterEach(() => { unmount?.(); vi.unstubAllGlobals(); vi.resetAllMocks(); });
async function mount(props: Record<string, unknown> = {}) {
  const view = mountStateComponent(PersonalTrainingStudyMode, { trainingId, ownerSessionId: owner, ...props });
  unmount = view.unmount; await flush(); return view;
}

it("opens the saved personal training in focus mode and restores the server draft", async () => {
  const view = await mount();
  expect(mocks.read).toHaveBeenCalledWith(trainingId, owner);
  expect(text(view.root)).toContain("洛必达专项");
  expect(text(view.root)).toContain("求极限");
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-answer")?.props.value).toBe("已暂存答案");
  expect(all(view.root).find((node) => node.props["data-testid"] === "training-full-paper")).toBeDefined();
});

it("uses the shared full-paper preview and routes answer entry back through the shared focus component", async () => {
  const completePlan = training();
  completePlan.item_count = 2;
  completePlan.remaining_count = 2;
  completePlan.items.push({ ...completePlan.items[0], item_id: "item-2", ordinal: 2, question_id: "question-2", question_version_id: "version-2", stem: "第二道专项题" });
  mocks.read.mockResolvedValueOnce(completePlan);
  const view = await mount();
  const fullPaper = all(view.root).find((node) => node.props["data-testid"] === "training-full-paper")!;
  (fullPaper.props.onClick as () => void)(); await flush();
  expect(all(view.root).find((node) => node.props["data-testid"] === "training-paper-list")).toBeDefined();
  expect(text(view.root)).toContain("洛必达法则");
  expect(text(view.root)).toContain("第二道专项题");
  expect(all(view.root).filter((node) => typeof node.props.id === "string" && String(node.props.id).startsWith("paper-item-")).length).toBe(2);
  expect(all(view.root).find((node) => node.props["data-testid"] === "training-progress-summary")).toBeDefined();
  expect(all(view.root).find((node) => node.props["data-testid"] === "training-paper-draft-answer")).toBeUndefined();
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-answer")).toBeUndefined();
  const answerEntry = all(view.root).find((node) => node.props["data-testid"] === "training-focus-item")!;
  (answerEntry.props.onClick as () => void)(); await flush();
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-answer")).toBeDefined();
});

it("submits only through the personal-training endpoint and reports isolated progress", async () => {
  const view = await mount();
  const input = all(view.root).find((node) => node.props["data-testid"] === "focus-answer")!;
  (input.props.onInput as (event: Event) => void)({ target: { value: "我的答案" } } as unknown as Event);
  const submit = all(view.root).find((node) => node.props["data-testid"] === "focus-submit")!;
  (submit.props.onClick as () => void)(); await flush();
  expect(mocks.saveDraft).toHaveBeenCalled();
  expect(mocks.answer).toHaveBeenCalledWith(trainingId, "item", expect.objectContaining({ owner_session_id: owner, raw_answer: "我的答案", selected_option: null }));
  expect(text(view.root)).toContain("本专项答案已提交：正确");
  expect(mocks.report).not.toHaveBeenCalled();
});

it("pauses only the personal training and makes the shared focus component read-only", async () => {
  const view = await mount();
  const pause = all(view.root).find((node) => node.props["data-testid"] === "pause-training")!;
  (pause.props.onClick as () => void)(); await flush();
  expect(mocks.transition).toHaveBeenCalledWith(trainingId, "pause", expect.objectContaining({ owner_session_id: owner, expected_version: 1 }));
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-stub")?.props["data-read-only"]).toBe("true");
  expect(text(view.root)).toContain("专项已暂停，进度已保留。");
  expect(mocks.answer).not.toHaveBeenCalled();
  expect(mocks.report).not.toHaveBeenCalled();
});

it("keeps the training active and retains an unsaved answer when draft persistence fails before pause", async () => {
  mocks.saveDraft.mockRejectedValueOnce(new Error("草稿存储暂不可用"));
  const view = await mount();
  const input = all(view.root).find((node) => node.props["data-testid"] === "focus-answer")!;
  (input.props.onInput as (event: Event) => void)({ target: { value: "刚输入但尚未提交" } } as unknown as Event);

  let pause = all(view.root).find((node) => node.props["data-testid"] === "pause-training")!;
  (pause.props.onClick as () => void)(); await flush();
  expect(mocks.transition).not.toHaveBeenCalled();
  expect(text(view.root)).toContain("草稿存储暂不可用");
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-answer")?.props.value).toBe("刚输入但尚未提交");

  pause = all(view.root).find((node) => node.props["data-testid"] === "pause-training")!;
  (pause.props.onClick as () => void)(); await flush();
  expect(mocks.saveDraft).toHaveBeenCalledTimes(2);
  expect(mocks.transition).toHaveBeenCalledTimes(1);
  expect(mocks.transition).toHaveBeenCalledWith(trainingId, "pause", expect.objectContaining({ owner_session_id: owner }));
});

it("does not leave the personal mode until the latest answer draft is saved", async () => {
  mocks.saveDraft.mockRejectedValueOnce(new Error("草稿保存失败"));
  const returned: boolean[] = [];
  const view = await mount({ onReturnToday: () => returned.push(true) });
  const input = all(view.root).find((node) => node.props["data-testid"] === "focus-answer")!;
  (input.props.onInput as (event: Event) => void)({ target: { value: "切换前的草稿" } } as unknown as Event);
  const back = all(view.root).find((node) => node.props["data-testid"] === "return-today-mode")!;
  (back.props.onClick as () => void)(); await flush();

  expect(returned).toEqual([]);
  expect(text(view.root)).toContain("草稿保存失败");
  expect(all(view.root).find((node) => node.props["data-testid"] === "focus-answer")?.props.value).toBe("切换前的草稿");
});

it("loads a completion report for a finished training only", async () => {
  mocks.read.mockResolvedValue(training({ status: "completed", completed_count: 1, remaining_count: 0 }));
  const view = await mount();
  expect(mocks.report).toHaveBeenCalledWith(trainingId, owner);
  expect(all(view.root).find((node) => node.props["data-testid"] === "personal-training-report")).toBeDefined();
});

it("ignores a stale completion report after the selected training changes", async () => {
  const oldId = "33333333-3333-4333-8333-333333333333";
  const newId = "44444444-4444-4444-8444-444444444444";
  const oldRead = deferred<PersonalTrainingView>();
  const oldReport = deferred<PersonalTrainingReport>();
  mocks.read.mockImplementation((id: string) => id === oldId
    ? oldRead.promise
    : Promise.resolve(training({ training_id: newId, title: "当前专项", status: "active" })));
  mocks.report.mockReturnValue(oldReport.promise);
  const state = reactive({ trainingId: oldId, ownerSessionId: owner });
  const ready: boolean[] = [];
  const host = mountStateComponent({
    setup: () => () => h(PersonalTrainingStudyMode, {
      trainingId: state.trainingId, ownerSessionId: state.ownerSessionId,
      onReady: (value: boolean) => ready.push(value),
    }),
  }, {});
  unmount = host.unmount;

  await flush();
  oldRead.resolve(training({ training_id: oldId, title: "过期专项", status: "completed" }));
  await flush();
  expect(mocks.report).toHaveBeenCalledWith(oldId, owner);

  state.trainingId = newId;
  await flush();
  expect(text(host.root)).toContain("当前专项");
  expect(ready).toEqual([true]);

  oldReport.resolve({ training_id: oldId, status: "completed", question_count: 1, submitted_count: 1,
    right_count: 0, wrong_count: 1, unknown_count: 0, wrong_knowledge_points: [],
    next_round_recommendation: null, evidence_scope: "personal_training" });
  await flush();

  expect(text(host.root)).toContain("当前专项");
  expect(all(host.root).find((node) => node.props["data-testid"] === "personal-training-report")).toBeUndefined();
  expect(ready).toEqual([true]);
});
