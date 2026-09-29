<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "../api/client";
import {
  appendQuestions,
  fetchAnswer,
  fetchKnowledgeTree,
  fetchKnowledgeNode,
  generateTodayPlan,
  fetchToday,
  submitSelfAssessment,
} from "../api/study";
import {
  BUDGET_OPTIONS,
  newIdempotencyKey,
  formatTime,
  roleLabel,
  typeLabel,
} from "../lib/labels";
import type {
  KnowledgeNodeView,
  PlanItemView,
  PracticeItemAnswer,
  SelfGrade,
  TodayActive,
  TodayResponse,
  TodaySetup,
} from "../types/practice";
import StudyFocus from "../components/StudyFocus.vue";
import KnowledgeQuestionPickerTree from "../components/KnowledgeQuestionPickerTree.vue";
import KnowledgeScopeTree from "../components/KnowledgeScopeTree.vue";
import { knowledgeSelection } from "../lib/knowledgeSelection";
import { StaleResponse, useAsyncTask } from "../composables/useAsyncTask";

// 统一状态（阶段 E）：今日学习、生成练习卷、查看答案三个异步动作都用
// `useAsyncTask`，页面不再自己发明 state/errorCode/errorMessage 三件套。
// 解构出同名的 ref，模板里 `state === 'loading'` 之类的绑定保持不变 ——
// 收敛的是**状态来源**，不是模板契约（28 个规格 testid 一个都不许动）。
const todayTask = useAsyncTask<TodayResponse>(null, {
  // 规格 2.5：kp_state_not_found 是「库里缺投影行」，提示先跑 seed.py 且不自动重试。
  errorMessages: {
    kp_state_not_found: "缺少掌握度投影行，请先运行 python scripts\\seed.py，然后刷新本页。",
  },
  fallbackMessage: "加载今日学习失败",
});
const { data: today, state, errorCode, errorMessage, run: runToday } = todayTask;

const generateTask = useAsyncTask<TodayResponse>(null, {
  errorMessages: {
    no_assessable_leaf_selected: "请先从知识树加入至少一个知识点。",
    question_pool_incomplete:
      "本次范围内有知识点的题库不足（题量、题型、考法或变式题未满足要求）。可调整范围移出该知识点，或先补充题库。",
    kp_state_not_found: "缺少掌握度投影行，请先运行 python scripts\\seed.py 再试。",
  },
  fallbackMessage: "生成失败",
});

const answerTask = useAsyncTask<PracticeItemAnswer>(null, {
  fallbackMessage: "查看答案失败",
});

const appendTask = useAsyncTask<TodayResponse>(null, {
  fallbackMessage: "追加失败",
});

// 今日学习数据的请求令牌，用于丢弃过期响应（见 load()）。
let loadToken = 0;
const route = useRoute();

// 准备页
const selectedKpIds = ref<string[]>([]);
const generating = ref(false);
const generateError = ref<string | null>(null);
// 时间预算：决定卷子总时长上限（轻量 45 / 标准 90 / 深度 120 分钟）。
const budget = ref<string>("standard");
// 章节只负责导航，只有可考核叶子能加入范围；默认采用后端推荐范围。
const showNodePicker = ref(false);
const scopeTree = ref<KnowledgeNodeView[]>([]);
const scopeSearch = ref("");
const scopeExpandedIds = ref(new Set<string>());
const scopeCollapsedIds = ref(new Set<string>());
const nodeLeaves = computed(() => flattenLeaves(scopeTree.value));
const scopeSelection = computed(() => knowledgeSelection(scopeTree.value, selectedKpIds.value));
const filteredScopeTree = computed(() => filterPickerTree(scopeTree.value, scopeSearch.value.trim()));
const nodePickerLoading = ref(false);
const nodePickerError = ref<string | null>(null);

watch(() => scopeSearch.value.trim(), () => {
  scopeCollapsedIds.value = new Set();
});

// 答题
const mode = ref<"focus" | "paper">("focus");
const answers = ref<Record<string, PracticeItemAnswer>>({});
// 答案数据可缓存，但是否展开是独立的界面状态；收起不能清掉已读取的答案。
const openAnswerIds = ref(new Set<string>());
const answerLoadingId = ref<string | null>(null);
const answerError = ref<string | null>(null);
const submittingId = ref<string | null>(null);
const gradeNotice = ref<Record<string, string>>({});
const gradeError = ref<Record<string, string>>({});
const rawAnswers = ref<Record<string, string>>({});
// 选择题选中的选项；只作为客观结果参考，不参与掌握度与毕业判定。
const selectedOptions = ref<Record<string, string>>({});
// 专注模式的本地光标：跳过只换到下一题，不改变服务端完成状态或掌握度。
const focusItemId = ref<string | null>(null);

// 追加练习题
const showPicker = ref(false);
const pickerTree = ref<KnowledgeNodeView[]>([]);
const pickerSearch = ref("");
const pickerLoading = ref(false);
const pickerError = ref<string | null>(null);
const pickerQuestions = ref<Record<string, { id: string; stem: string; is_variant: boolean }[]>>({});
const pickerQuestionLoadingIds = ref(new Set<string>());
const pickerSelected = ref<string[]>([]);
const pickerExpandedIds = ref(new Set<string>());
const pickerCollapsedIds = ref(new Set<string>());
const appending = ref(false);
const filteredPickerTree = computed(() => filterPickerTree(pickerTree.value, pickerSearch.value.trim()));

watch(() => pickerSearch.value.trim(), (query, previous) => {
  if (query !== previous) pickerCollapsedIds.value = new Set();
});

const setup = computed<TodaySetup | null>(() =>
  today.value && today.value.status === "setup" ? today.value : null,
);
const selectedKpEntries = computed(() => selectedKpIds.value.map((id) => {
  const recommended = setup.value?.recommendations.find((item) => item.kp_id === id);
  const fromTree = nodeLeaves.value.find((node) => node.id === id);
  const path = scopeSelection.value.paths.get(id);
  return { id, name: recommended?.name ?? fromTree?.name ?? "知识点", path: path?.names.slice(0, -1).join(" › ") ?? "" };
}));

async function locateSelectedKp(id: string): Promise<void> {
  scopeSearch.value = "";
  const ancestors = scopeSelection.value.paths.get(id)?.ancestorIds ?? [];
  scopeExpandedIds.value = new Set([...scopeExpandedIds.value, ...ancestors]);
  scopeCollapsedIds.value = new Set([...scopeCollapsedIds.value].filter(item => !ancestors.includes(item)));
  await nextTick();
  const button = document.getElementById(`scope-leaf-${id}`);
  button?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  button?.focus({ preventScroll: true });
}
const active = computed<TodayActive | null>(() =>
  today.value && today.value.status !== "setup" ? (today.value as TodayActive) : null,
);
// 旧卷和追加题也按题型呈现，同题型保留原卷次序。
const questionTypeRank: Record<string, number> = {
  single_choice: 0,
  multiple_choice: 0,
  fill_blank: 1,
  calculation: 2,
  proof: 2,
  subjective: 2,
  external_exam: 3,
};
const orderedItems = computed(() => [...(active.value?.items ?? [])].sort((a, b) =>
  (questionTypeRank[a.question_type] ?? 3) - (questionTypeRank[b.question_type] ?? 3)
  || a.ordinal - b.ordinal,
));
const remainingItems = computed(() => orderedItems.value.filter((item) => !item.completed));
const currentItem = computed<PlanItemView | null>(() =>
  remainingItems.value.find((item) => item.id === focusItemId.value)
  ?? remainingItems.value[0]
  ?? null,
);

async function load(): Promise<void> {
  // 请求令牌：连点自评/切模式会并发触发 load，晚发出的请求可能先返回。
  // 用它保证只有**最后一次**请求的结果能写回，避免旧数据覆盖新数据。
  const token = ++loadToken;
  // `keepPreviousData`：只在**首次**加载时把整页切成 loading 态。
  //
  // 为什么：自评提交成功后要重新拉取今日学习，而 `study-active`（含全卷 paper-list）
  // 只在 state==="success" 时才渲染。若刷新时先切 loading，整块内容会被从 DOM 里
  // 摘掉再装回来 —— 用户在这段窗口里点「全卷模式」会看到卷子消失，
  // 自动化里表现为 paper-list 时有时无（默认 5 秒断言超时被判失败）。
  // 已有数据时保持现有视图，刷新在后台完成。
  await runToday(
    async () => {
      const data = await fetchToday();
      // 过期响应直接丢弃：既不写数据，也不改状态。
      if (token !== loadToken) throw new StaleResponse();
      return data;
    },
    { keepPreviousData: true },
  );
  if (token !== loadToken) return;
  const data = today.value;
  if (data && state.value === "success") {
    if (data.status === "setup") {
      // 默认采用推荐范围；用户需要时再打开调整面板增减叶子。
      selectedKpIds.value = data.recommendations.map((item) => item.kp_id);
    }
  }
}

function toggleKp(kpId: string): void {
  const index = selectedKpIds.value.indexOf(kpId);
  if (index >= 0) selectedKpIds.value.splice(index, 1);
  else selectedKpIds.value.push(kpId);
}

async function generate(): Promise<void> {
  if (selectedKpIds.value.length === 0) {
    // 规格 2.5：no_assessable_leaf_selected —— 生成按钮禁用并提示先选知识点。
    generateError.value = "请至少选择一个知识点（没有选中时后端也会拒绝生成）";
    return;
  }
  generating.value = true;
  generateError.value = null;
  const result = await generateTask.run(() => generateTodayPlan(selectedKpIds.value, budget.value));
  if (result) {
    today.value = result;
    generating.value = false;
    return;
  }
  // 规格 2.5：**只按 code 决定行为**，message 只当文案。
  // 未列出的 code 一律走兜底（见下面的 default），
  // 绝不在这里猜测「重建、删除、跳转」之类的业务动作。
  switch (generateTask.errorCode.value) {
    case "plan_already_generated":
      // 今天已经生成过练习卷。**不显示「重新生成」**，而是重新读今日计划、
      // 切到答题页 —— 用户要的是继续做题，不是再要一张新卷。
      generateError.value = "今天已经有练习卷了，正在为你打开。";
      generating.value = false;
      await load();
      return;
    case null:
      // 没有错误码（网络类失败）：用统一状态给的兜底文案。
      generateError.value = generateTask.errorMessage.value ?? "生成失败";
      break;
    default:
      // 兜底：保留用户调整过的知识点与预算，只显示后端文案 + 普通重试。
      generateError.value = generateTask.errorMessage.value ?? "生成失败";
  }
  generating.value = false;
}

function isAnswerOpen(itemId: string): boolean {
  return openAnswerIds.value.has(itemId);
}

function setAnswerOpen(itemId: string, open: boolean): void {
  const next = new Set(openAnswerIds.value);
  if (open) next.add(itemId);
  else next.delete(itemId);
  openAnswerIds.value = next;
}

async function toggleAnswer(item: TodayActive["items"][number]): Promise<void> {
  // answerTask 是单实例的异步任务；并发读取两道题会让较早请求变成 stale。
  // 同一时刻只允许一个答案请求，避免共享 loading 标记与结果互相覆盖。
  if (answerLoadingId.value !== null) return;
  if (isAnswerOpen(item.id)) {
    setAnswerOpen(item.id, false);
    return;
  }
  if (answers.value[item.id]) {
    setAnswerOpen(item.id, true);
    return;
  }
  answerLoadingId.value = item.id;
  answerError.value = null;
  const data = await answerTask.run(() => fetchAnswer(item.id));
  if (data) {
    answers.value[item.id] = data;
    setAnswerOpen(item.id, true);
  }
  else answerError.value = answerTask.errorMessage.value;
  answerLoadingId.value = null;
}

async function grade(item: PlanItemView, selfGrade: SelfGrade): Promise<void> {
  submittingId.value = item.id;
  delete gradeError.value[item.id];
  try {
    const result = await submitSelfAssessment(
      item.id,
      selfGrade,
      newIdempotencyKey(`item-${item.id}`),
      rawAnswers.value[item.id],
      selectedOptions.value[item.id],
    );
    // 后端返回的原因码决定提示；前端不自己判断是否毕业。
    if (selfGrade === "skip") {
      gradeNotice.value[item.id] = "已跳过本题，未记录掌握情况。";
      if (mode.value === "focus") {
        const index = remainingItems.value.findIndex((candidate) => candidate.id === item.id);
        const next = remainingItems.value[(index + 1) % remainingItems.value.length];
        focusItemId.value = next?.id ?? null;
      }
    } else {
      gradeNotice.value[item.id] = item.is_external_reference
        ? "已记录。标记“已掌握”的不同真题会计入该知识点毕业进度。"
        : "已记录，可在知识树查看掌握情况。";
      // 只有在**专注模式**下才自动跳到下一道未完成题。
      //
      // 为什么不能无条件切 focus：用户可以在全卷模式下逐题自评，
      // 提交后把他从全卷弹回专注，等于打断他正在做的事；
      // 而且这一刻页面正在刷新，视图切换更容易让人以为「卷子丢了」。
      const wasFocus = mode.value === "focus";
      await load();
      if (wasFocus) mode.value = "focus";
    }
  } catch (error) {
    if (!(error instanceof ApiError)) {
      gradeError.value[item.id] = "提交失败";
      return;
    }
    // 规格 2.5：只按 code 决定行为。
    switch (error.code) {
      case "practice_item_already_assessed":
        // 同一题换了幂等键重复提交：以**服务端已完成结果**为准刷新，
        // 不在这里再次累计进度，也不重复弹提示。
        gradeNotice.value[item.id] = "这道题之前已经提交过，已刷新为服务端记录的结果。";
        await load();
        return;
      case "practice_item_not_found":
        // 题目被删或卷已重建：专注模式跳到下一道未完成题，而不是停在死题上。
        gradeError.value[item.id] = "这道题已不在今天的练习卷里，已跳到下一道未完成题。";
        await load();
        return;
      case "plan_not_active":
        gradeError.value[item.id] = "今日练习已结束，无法再提交自评。已刷新计划状态。";
        await load();
        return;
      case "kp_state_not_found":
        gradeError.value[item.id] = "缺少掌握度投影行，请先运行 python scripts\\seed.py。";
        return;
      default:
        gradeError.value[item.id] = `${error.message}（${error.code ?? "未知错误"}）`;
    }
  } finally {
    submittingId.value = null;
  }
}

function openPicker(): void {
  showPicker.value = true;
  pickerSearch.value = "";
  pickerError.value = null;
  pickerSelected.value = [];
  pickerExpandedIds.value = new Set();
  pickerCollapsedIds.value = new Set();
  void loadPickerTree();
}

function flattenLeaves(nodes: KnowledgeNodeView[]): KnowledgeNodeView[] {
  const result: KnowledgeNodeView[] = [];
  const walk = (items: KnowledgeNodeView[]) => {
    for (const node of items) {
      if (node.is_assessable) result.push(node);
      walk(Array.isArray(node.children) ? node.children : []);
    }
  };
  walk(nodes);
  return result;
}

function filterPickerTree(nodes: KnowledgeNodeView[], query: string): KnowledgeNodeView[] {
  const normalized = query.toLocaleLowerCase();
  if (!normalized) return nodes;
  const filtered: KnowledgeNodeView[] = [];
  for (const node of nodes) {
    const matches = `${node.name} ${node.code}`.toLocaleLowerCase().includes(normalized);
    const children = filterPickerTree(Array.isArray(node.children) ? node.children : [], query);
    if (matches) filtered.push(node);
    else if (children.length > 0) filtered.push({ ...node, children });
  }
  return filtered;
}

function findNodePath(
  nodes: KnowledgeNodeView[],
  targetId: string,
  ancestors: KnowledgeNodeView[] = [],
): KnowledgeNodeView[] | null {
  for (const node of nodes) {
    const path = [...ancestors, node];
    if (node.id === targetId) return path;
    const found = findNodePath(Array.isArray(node.children) ? node.children : [], targetId, path);
    if (found) return found;
  }
  return null;
}

async function loadPickerTree(): Promise<void> {
  if (pickerTree.value.length > 0) return;
  pickerLoading.value = true;
  pickerError.value = null;
  try {
    const data = await fetchKnowledgeTree();
    pickerTree.value = Array.isArray(data.nodes) ? data.nodes : [];
  } catch (error) {
    pickerError.value = error instanceof ApiError ? error.message : "加载知识树失败";
  } finally {
    pickerLoading.value = false;
  }
}

/** 准备页保留章节层级；深链接预选时不自动打开调整面板。 */
async function loadNodeLeaves(): Promise<void> {
  if (scopeTree.value.length > 0 || nodePickerLoading.value) return;
  nodePickerLoading.value = true;
  nodePickerError.value = null;
  try {
    const data = await fetchKnowledgeTree();
    scopeTree.value = Array.isArray(data.nodes) ? data.nodes : [];
    // 默认露出学科下的章节，不把整棵树一次铺开。
    scopeExpandedIds.value = new Set(scopeTree.value.map((node) => node.id));
  } catch (error) {
    nodePickerError.value = error instanceof ApiError ? error.message : "加载知识树失败";
  } finally {
    nodePickerLoading.value = false;
  }
}

async function openNodePicker(): Promise<void> {
  showNodePicker.value = !showNodePicker.value;
  if (showNodePicker.value) await loadNodeLeaves();
}

function toggleScopeBranch(node: KnowledgeNodeView): void {
  const expanded = new Set(scopeExpandedIds.value);
  const collapsed = new Set(scopeCollapsedIds.value);
  const isOpen = !collapsed.has(node.id) && (expanded.has(node.id) || scopeSearch.value.trim().length > 0);
  if (isOpen) {
    expanded.delete(node.id);
    collapsed.add(node.id);
  } else {
    expanded.add(node.id);
    collapsed.delete(node.id);
  }
  scopeExpandedIds.value = expanded;
  scopeCollapsedIds.value = collapsed;
}

/** 把某个叶子加入 / 移出今天的选点。 */
function toggleNodeSelection(kpId: string): void {
  toggleKp(kpId);
}

async function loadPickerQuestions(kpId: string): Promise<void> {
  if (pickerQuestions.value[kpId] || pickerQuestionLoadingIds.value.has(kpId)) return;
  pickerError.value = null;
  const loading = new Set(pickerQuestionLoadingIds.value);
  loading.add(kpId);
  pickerQuestionLoadingIds.value = loading;
  try {
    const detail = await fetchKnowledgeNode(kpId);
    const inPaper = new Set(active.value?.items.map((item) => item.question_id) ?? []);
    pickerQuestions.value[kpId] = detail.questions
      .filter((question) => !inPaper.has(question.id))
      .map((question) => ({ id: question.id, stem: question.stem, is_variant: question.is_variant }));
  } catch (error) {
    pickerError.value = error instanceof ApiError ? error.message : "加载题库失败";
  } finally {
    const next = new Set(pickerQuestionLoadingIds.value);
    next.delete(kpId);
    pickerQuestionLoadingIds.value = next;
  }
}

function togglePickerNode(node: KnowledgeNodeView): void {
  const next = new Set(pickerExpandedIds.value);
  const collapsed = new Set(pickerCollapsedIds.value);
  const hasChildren = Array.isArray(node.children) && node.children.length > 0;
  const autoExpanded = hasChildren && pickerSearch.value.trim().length > 0 && !collapsed.has(node.id);
  const expanded = !collapsed.has(node.id) && (next.has(node.id) || autoExpanded);
  if (expanded) {
    next.delete(node.id);
    collapsed.add(node.id);
  } else {
    next.add(node.id);
    collapsed.delete(node.id);
    pickerError.value = null;
    if (node.is_assessable && (!Array.isArray(node.children) || node.children.length === 0)) {
      void loadPickerQuestions(node.id);
    }
  }
  pickerExpandedIds.value = next;
  pickerCollapsedIds.value = collapsed;
}

function togglePickerQuestion(questionId: string): void {
  const index = pickerSelected.value.indexOf(questionId);
  if (index >= 0) pickerSelected.value.splice(index, 1);
  else pickerSelected.value.push(questionId);
}

async function confirmAppend(): Promise<void> {
  if (!active.value || pickerSelected.value.length === 0) return;
  appending.value = true;
  pickerError.value = null;
  const result = await appendTask.run(() => appendQuestions(active.value!.plan_id, pickerSelected.value));
  if (result && result.status !== "setup") {
    today.value = result;
    const inPlan = new Set(result.items.map((item) => item.question_id));
    for (const [kpId, questions] of Object.entries(pickerQuestions.value)) {
      pickerQuestions.value[kpId] = questions.filter((question) => !inPlan.has(question.id));
    }
    showPicker.value = false;
    pickerSelected.value = [];
    appending.value = false;
    return;
  }
  // 规格 2.5：往已结束的卷追加 → 提示「今日练习已结束」并刷新计划，
  // **绝不在本地插题**（本地插入会造出服务端并不存在的题目）。
  switch (appendTask.errorCode.value) {
    case "plan_not_active":
      pickerError.value = "今日练习已结束，无法再追加题目。已刷新计划状态。";
      showPicker.value = false;
      appending.value = false;
      await load();
      return;
    case "plan_not_found":
      // 计划 id 失效：回到准备页并重新读今日计划。
      pickerError.value = "这个练习卷已不存在，已重新读取今日计划。";
      showPicker.value = false;
      appending.value = false;
      await load();
      return;
    default:
      pickerError.value = appendTask.errorMessage.value ?? "追加失败";
  }
  appending.value = false;
}

onMounted(async () => {
  await load();
  const kpId = typeof route.query.kp_id === "string" ? route.query.kp_id : null;
  if (!kpId || state.value !== "success") return;
  if (setup.value) {
    await loadNodeLeaves();
    if (nodeLeaves.value.some((node) => node.id === kpId)) {
      selectedKpIds.value = [kpId];
    }
  } else if (active.value) {
    openPicker();
    await loadPickerTree();
    const path = findNodePath(pickerTree.value, kpId);
    if (path) {
      pickerExpandedIds.value = new Set(path.map((node) => node.id));
      if (path.at(-1)?.is_assessable) await loadPickerQuestions(kpId);
    }
  }
});
</script>

<template>
  <section class="page">
    <p v-if="state === 'loading' && !today" class="state state--loading" data-testid="study-loading">正在加载今日学习…</p>

    <div v-if="state === 'error' && !today" class="state state--error" data-testid="study-error">
      <p>{{ errorMessage }}</p>
      <p v-if="errorCode" class="state__code">错误码：{{ errorCode }}</p>
      <button type="button" @click="load">重试</button>
    </div>
    <p v-if="state === 'error' && today" class="state state--error" role="alert" data-testid="study-refresh-error">
      刷新失败，当前练习内容仍保留：{{ errorMessage }} <button type="button" @click="load">重试</button>
    </p>

    <!-- 准备页：没有用户确认就不创建计划 -->
    <div v-if="setup" class="study-setup" data-testid="study-setup">
      <div class="study-setup-intro">
        <span>{{ setup.study_date }} · 今日练习</span>
        <h2>今天的练习</h2>
      </div>
      <div class="study-setup-layout">
        <section class="study-select-panel">
          <header class="study-panel-heading">
            <div><h2>练习范围</h2></div>
            <button type="button" data-testid="tree-kp-picker-open" :aria-expanded="showNodePicker" aria-controls="study-scope-picker" @click="openNodePicker">{{ showNodePicker ? "收起范围" : "调整范围" }}</button>
          </header>
          <!-- 调整只在主动打开时出现，紧贴入口以免落到首屏之外。 -->
          <div v-if="showNodePicker" id="study-scope-picker" class="picker" data-testid="tree-kp-picker">
            <label class="picker-search">
              <span class="sr-only">搜索练习范围</span>
              <input v-model="scopeSearch" type="search" aria-label="搜索练习范围" placeholder="搜索章节或知识点" data-testid="scope-picker-search" />
            </label>
            <p class="picker-hint">展开章节，加入或移出要练习的知识点。</p>
            <ul v-if="!nodePickerLoading && selectedKpEntries.length" class="scope-selected-list" aria-label="已选知识点及所属路径">
              <li v-for="item in selectedKpEntries" :key="item.id" :data-testid="`scope-selected-${item.id}`">
                <span><strong>{{ item.name }}</strong><small>{{ item.path || '所属路径暂不可用' }}</small></span>
                <button v-if="item.path" type="button" :aria-label="'定位' + item.name" @click="locateSelectedKp(item.id)">定位</button>
                <button type="button" :aria-label="'从范围移出' + item.name" @click="toggleNodeSelection(item.id)">移出</button>
              </li>
            </ul>
            <p v-if="nodePickerLoading" class="state state--loading">正在加载知识树…</p>
            <div v-else-if="nodePickerError" class="form-error" role="alert">
              <p>{{ nodePickerError }}</p>
              <button type="button" @click="loadNodeLeaves">重新加载</button>
            </div>
            <div v-else-if="filteredScopeTree.length" class="scope-tree-window" data-testid="scope-tree-window" tabindex="0" aria-label="练习范围知识树，可滚动">
              <KnowledgeScopeTree
                :nodes="filteredScopeTree"
                :selected-ids="selectedKpIds"
                :selected-counts="scopeSelection.counts"
                :expanded-ids="scopeExpandedIds"
                :collapsed-ids="scopeCollapsedIds"
                :auto-expand="scopeSearch.trim().length > 0"
                :level="1"
                @toggle-branch="toggleScopeBranch"
                @toggle-selection="toggleNodeSelection"
              />
            </div>
            <p v-else-if="!nodePickerLoading && scopeSearch.trim()" class="state state--empty" data-testid="scope-picker-empty">
              没有找到匹配的章节或知识点。
            </p>
            <p v-else-if="!nodePickerLoading && !nodePickerError" class="state state--empty">
              知识树里还没有可考核的叶子节点。
            </p>
            <div class="scope-picker-footer">
              <span aria-live="polite">已选 {{ selectedKpIds.length }} 个知识点</span>
              <button type="button" data-testid="close-tree-kp-picker" @click="showNodePicker = false">完成</button>
            </div>
          </div>
          <ul v-if="selectedKpEntries.length && !showNodePicker" class="recommend-list" data-testid="recommended-kp">
            <li v-for="(item, index) in selectedKpEntries" :key="item.id" class="selected-kp-row" :data-testid="'recommend-' + item.id">
              <span class="selected-kp-row__number">{{ String(index + 1).padStart(2, "0") }}</span>
              <span class="recommend-name">{{ item.name }}<small v-if="item.path" class="selected-kp-path">{{ item.path }}</small></span>
            </li>
          </ul>
          <p v-if="!selectedKpEntries.length" class="state state--empty">
            暂无知识点，点击“调整范围”从知识树选择。
          </p>
        </section>
        <aside class="study-config-panel">
          <header class="study-panel-heading"><div><h2>练习时长</h2></div></header>
          <fieldset class="budget" data-testid="budget-picker">
            <legend class="sr-only">时间预算</legend>
            <label v-for="option in BUDGET_OPTIONS" :key="option.value" class="budget-option" :class="{ 'budget-option--selected': budget === option.value }">
              <input
                type="radio"
                name="budget"
                :value="option.value"
                :checked="budget === option.value"
                :data-testid="'budget-' + option.value"
                @change="budget = option.value"
              />
              <span class="budget-option__name">{{ option.hint }}</span>
            </label>
          </fieldset>
          <div class="study-setup-action">
            <p class="hint" data-testid="selected-kp-count">本次包含 {{ selectedKpIds.length }} 个知识点</p>
            <button type="button" class="setup-generate" :disabled="generating || selectedKpIds.length === 0" data-testid="generate-plan" @click="generate">
              {{ generating ? "正在准备…" : "开始今日练习" }}
            </button>
          </div>
          <p v-if="generateError" class="form-error" data-testid="plan-generate-error">{{ generateError }}</p>
        </aside>
      </div>
    </div>

    <!-- 答题页 -->
    <div v-if="active" class="study-active" data-testid="study-active">
      <div class="study-plan-overview">
        <div class="study-progress">
      <p class="state" data-testid="study-status">
        状态：{{ active.status === "completed" ? "今日已完成" : "进行中" }}
        （{{ active.completed_count }} / {{ active.total_count }}）
      </p>

      <!--
        今日完成态的显式锚点（规格固定的 study-completed）。
        它**只在后端说 completed 时**出现 —— 验收要求「跳过不得让页面
        显示今日完成」，所以这个元素必须严格跟着服务端状态，不能由前端推断。
      -->
      <p v-if="active.status === 'completed'" class="notice" data-testid="study-completed">
        今日练习已完成，可以在「阅览全卷」里回看，或追加练习题继续练。
      </p>

      <!-- 卷子构成：题型分布与预计时长（由后端按缺口组织，页面只展示） -->
        </div>
      <section class="paper-summary" data-testid="paper-summary">
        <p class="paper-summary__line">
          <strong>今日练习卷</strong>
          <span class="tag tag--muted">共 {{ active.total_count }} 道</span>
          <span class="tag tag--muted">预计 {{ active.estimated_minutes }} 分钟</span>
          <span v-if="active.remaining_minutes > 0" class="tag">
            待做 {{ active.remaining_minutes }} 分钟
          </span>
        </p>
        <p class="paper-summary__types">
          <span v-for="(count, type) in active.type_summary" :key="type" class="tag">
            {{ typeLabel(String(type)) }} {{ count }} 道
          </span>
        </p>
      </section>

      </div>
      <nav class="mode-switch">
        <button
          type="button"
          :class="{ active: mode === 'focus' }"
          data-testid="mode-focus"
          @click="mode = 'focus'"
        >
          专注模式
        </button>
        <button
          type="button"
          :class="{ active: mode === 'paper' }"
          data-testid="full-paper"
          @click="mode = 'paper'"
        >
          阅览全卷
        </button>
      </nav>

      <div class="study-active-layout">
        <div class="study-active-main">
      <!-- 专注模式：一次一道未完成题 -->
      <section
        v-if="mode === 'focus' && currentItem && currentItem.is_external_reference"
        class="external-exam-task"
        data-testid="focus-external-exam-task"
      >
        <p class="eyebrow">历年真题 · {{ currentItem.exam_reference?.subject }}</p>
        <h2>{{ currentItem.exam_reference?.year }} 年第 {{ currentItem.exam_reference?.question_number }} 题</h2>
        <p class="external-exam-task__topic">{{ currentItem.exam_reference?.topic_label || currentItem.kp_name }}</p>
        <p class="hint">请打开原卷完成这道题，再按实际掌握情况自评。自评为“已掌握”时，这道不同真题会作为 {{ currentItem.kp_name }} 的毕业证据。</p>
        <div class="external-exam-task__sources">
          <a v-if="currentItem.exam_reference?.question_source_url" :href="currentItem.exam_reference.question_source_url" target="_blank" rel="noopener noreferrer">打开题目来源 ↗</a>
          <span>本地原卷：桌面 / 考研知识点 / {{ currentItem.exam_reference?.local_folder }}</span>
        </div>
        <div class="actions actions--grades">
          <button type="button" :disabled="submittingId === currentItem.id" @click="grade(currentItem, 'mastered')">已掌握</button>
          <button type="button" :disabled="submittingId === currentItem.id" @click="grade(currentItem, 'partial')">部分掌握</button>
          <button type="button" :disabled="submittingId === currentItem.id" @click="grade(currentItem, 'not_mastered')">未掌握</button>
          <button type="button" :disabled="submittingId === currentItem.id" @click="grade(currentItem, 'skip')">跳过</button>
        </div>
        <p v-if="gradeNotice[currentItem.id]" class="notice" data-testid="external-exam-focus-notice">{{ gradeNotice[currentItem.id] }}</p>
        <p v-if="gradeError[currentItem.id]" class="form-error">{{ gradeError[currentItem.id] }}</p>
      </section>

      <StudyFocus
        v-else-if="mode === 'focus'"
        :item="currentItem"
        :answer="currentItem ? answers[currentItem.id] : undefined"
        :answer-open="currentItem ? isAnswerOpen(currentItem.id) : false"
        :answer-loading="answerLoadingId !== null"
        :answer-error="answerError"
        :submitting="submittingId === currentItem?.id"
        :notice="currentItem ? gradeNotice[currentItem.id] : undefined"
        :grade-error="currentItem ? gradeError[currentItem.id] : undefined"
        :remaining="remainingItems.length"
        :display-number="orderedItems.findIndex((item) => item.id === currentItem?.id) + 1"
        :raw-answer="currentItem ? rawAnswers[currentItem.id] ?? '' : ''"
        :selected-option="currentItem ? selectedOptions[currentItem.id] : undefined"
        @reveal="currentItem && toggleAnswer(currentItem)"
        @grade="(g: SelfGrade) => currentItem && grade(currentItem, g)"
        @update:rawAnswer="(v: string) => currentItem && (rawAnswers[currentItem.id] = v)"
        @update:selectedOption="(v: string) => currentItem && (selectedOptions[currentItem.id] = v)"
      />

      <!-- 全卷模式：按题型显示全部，包括已完成 -->
      <ol v-else class="paper-list" data-testid="paper-list">
        <li v-for="(item, index) in orderedItems" :key="item.id" class="paper-item">
          <header>
            <strong>第 {{ index + 1 }} 题</strong>
            <span class="tag tag--muted">{{ typeLabel(item.question_type) }}</span>
            <span class="tag tag--muted">{{ item.completed ? "已完成" : "未完成" }}</span>
          </header>
          <div class="paper-question-layout">
            <div class="paper-question-main">
          <template v-if="item.is_external_reference && item.exam_reference">
            <section class="external-exam-task external-exam-task--paper" :data-testid="`external-exam-${item.id}`">
              <p class="eyebrow">{{ item.exam_reference.subject }} · {{ item.exam_reference.year }} 年</p>
              <h2>第 {{ item.exam_reference.question_number }} 题</h2>
              <p class="external-exam-task__topic">{{ item.exam_reference.topic_label || item.kp_name }}</p>
              <div class="external-exam-task__sources">
                <a v-if="item.exam_reference.question_source_url" :href="item.exam_reference.question_source_url" target="_blank" rel="noopener noreferrer">打开题目来源 ↗</a>
                <a v-if="item.exam_reference.topic_source_url" :href="item.exam_reference.topic_source_url" target="_blank" rel="noopener noreferrer">查看考点来源 ↗</a>
                <span>本地原卷：桌面 / 考研知识点 / {{ item.exam_reference.local_folder }}</span>
              </div>
              <p class="hint">原卷题干不在系统内。完成后按实际表现自评；标记“已掌握”的不同真题会计入该知识点毕业条件。</p>
              <div class="actions">
                <template v-if="!item.completed">
                  <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'mastered')">已掌握</button>
                  <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'partial')">部分掌握</button>
                  <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'not_mastered')">未掌握</button>
                  <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'skip')">跳过</button>
                </template>
              </div>
              <p v-if="gradeNotice[item.id]" class="notice">{{ gradeNotice[item.id] }}</p>
              <p v-if="gradeError[item.id]" class="form-error">{{ gradeError[item.id] }}</p>
            </section>
          </template>
          <template v-else>
          <details class="question-meta">
            <summary>题目信息</summary>
            <div>{{ item.kp_name }} · {{ roleLabel(item.question_role) }} · 预计 {{ item.estimated_minutes }} 分钟</div>
            <div v-if="item.is_variant || item.is_review">{{ item.is_variant ? "变式题" : "" }}{{ item.is_variant && item.is_review ? " · " : "" }}{{ item.is_review ? "复测" : "" }}</div>
            <div v-if="item.skill_tags.length">考法：{{ item.skill_tags.join("、") }}</div>
          </details>
          <p class="stem">{{ item.stem }}</p>
          <ul v-if="item.options" class="options">
            <li v-for="(text, key) in item.options" :key="key">
              <label class="option-choice">
                <input
                  type="radio"
                  :name="`paper-option-${item.id}`"
                  :value="key"
                  :checked="selectedOptions[item.id] === key"
                  :disabled="item.completed"
                  :data-testid="`paper-option-${item.id}-${key}`"
                  @change="selectedOptions[item.id] = key"
                />
                <span>{{ key }}. {{ text }}</span>
              </label>
            </li>
          </ul>

          <div class="actions">
            <template v-if="!item.completed">
              <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'mastered')">已掌握</button>
              <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'partial')">部分掌握</button>
              <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'not_mastered')">未掌握</button>
              <button type="button" :disabled="submittingId === item.id" @click="grade(item, 'skip')">跳过</button>
            </template>
          </div>
          <p v-if="gradeNotice[item.id]" class="notice" data-testid="paper-notice">{{ gradeNotice[item.id] }}</p>
          <p v-if="gradeError[item.id]" class="form-error">{{ gradeError[item.id] }}</p>
          </template>
            </div>
            <aside v-if="!item.is_external_reference" class="paper-answer-pane" aria-label="答案详解">
              <button type="button" :disabled="answerLoadingId !== null" :aria-expanded="isAnswerOpen(item.id)" :aria-controls="`paper-answer-${item.id}`" @click="toggleAnswer(item)">{{ answerLoadingId === item.id ? "加载中…" : isAnswerOpen(item.id) ? "收起答案详解" : "查看答案详解" }}</button>
              <div v-if="isAnswerOpen(item.id) && answers[item.id]" :id="`paper-answer-${item.id}`" class="answer-box" :data-testid="`answer-${item.id}`">
                <p><strong>参考答案：</strong>{{ answers[item.id].correct_answer ?? "（无标准答案，请自行对照解析）" }}</p>
                <p><strong>解析：</strong>{{ answers[item.id].explanation }}</p>
              </div>
            </aside>
          </div>
        </li>
      </ol>

        </div>
        <aside class="study-active-aside">
      <section class="summary">
        <h2>今日涉及的知识点</h2>
        <ul data-testid="today-kp-summary">
          <li v-for="kp in active.summary_kps" :key="kp.kp_id">
            {{ kp.name }}：{{ kp.completed_count }} / {{ kp.total_count }}
          </li>
        </ul>
      </section>

      <div class="actions">
        <button type="button" data-testid="append-questions" @click="openPicker">追加练习题</button>
      </div>

        </aside>
      </div>
      <!-- 追加：只从已有题库选题，加到卷尾，不重洗不生成 -->
      <div v-if="showPicker" class="picker" data-testid="question-picker">
        <h2>从题库追加到卷尾</h2>
        <label class="picker-search">
          <span class="sr-only">搜索知识点</span>
          <input
            v-model="pickerSearch"
            type="search"
            aria-label="搜索知识点"
            placeholder="搜索知识点名称"
            data-testid="question-picker-search"
          />
        </label>
        <p class="picker-hint">按知识树展开章节，选择知识点后查看可追加题目。</p>
        <p v-if="pickerLoading" class="state state--loading">正在加载知识树…</p>
        <p v-if="pickerError" class="form-error">{{ pickerError }}</p>
        <p v-if="!pickerLoading && filteredPickerTree.length === 0" class="state state--empty" data-testid="question-picker-empty">
          没有找到匹配的知识点。
        </p>
        <KnowledgeQuestionPickerTree
          v-if="filteredPickerTree.length > 0"
          :nodes="filteredPickerTree"
          :expanded-ids="pickerExpandedIds"
          :collapsed-ids="pickerCollapsedIds"
          :questions="pickerQuestions"
          :question-loading-ids="pickerQuestionLoadingIds"
          :selected-question-ids="pickerSelected"
          :auto-expand-branches="pickerSearch.trim().length > 0"
          :level="1"
          @toggle-node="togglePickerNode"
          @toggle-question="togglePickerQuestion"
        />
        <div class="actions">
          <button
            type="button"
            :disabled="appending || pickerSelected.length === 0"
            data-testid="confirm-append"
            @click="confirmAppend"
          >
            {{ appending ? "追加中…" : `确认追加（${pickerSelected.length}）` }}
          </button>
          <button type="button" @click="showPicker = false">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>


<style scoped>
.study-setup-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(270px, .75fr);
  align-items: start;
  gap: 18px;
  margin-top: 20px;
}
.study-select-panel,
.study-config-panel,
.study-plan-overview,
.study-active-aside {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}
.study-select-panel { padding: 18px; }
.study-config-panel {
  position: sticky;
  top: calc(var(--topbar-height) + 18px);
  padding: 18px;
}
.study-panel-heading {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.study-panel-heading > span {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 600;
}
.study-panel-heading h2 { margin: 0; font-size: 15px; font-weight: 600; }
.study-panel-heading p { margin: 2px 0 0; color: var(--text-secondary); font-size: 12px; }
.study-select-panel .state--setup {
  margin: 16px 0 12px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
}
.study-select-panel .recommend-list { margin-bottom: 0; }
.study-config-panel .budget {
  margin: 17px 0 16px;
  padding: 0;
  border: 0;
  background: transparent;
}
.study-config-panel .budget legend { margin-bottom: 5px; font-weight: 600; }
.study-config-panel .budget-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 43px;
  margin: 0;
  border-bottom: 1px solid var(--border);
}
.study-config-panel .budget-option:last-child { border-bottom: 0; }
.study-config-panel .budget-option .hint { margin-left: auto; }
.study-config-panel .actions { display: flex; flex-direction: column-reverse; gap: 8px; }
.study-config-panel .actions button { width: 100%; margin: 0; }
.study-config-panel [data-testid="generate-plan"] { border-color: #2d2e30; color: #fff; background: #2d2e30; }
.study-config-panel [data-testid="generate-plan"]:hover:not(:disabled) { background: #161719; }
.study-config-panel [data-testid="selected-kp-count"] { margin: 13px 0 0; line-height: 1.5; }
.study-setup > .picker { margin-top: 18px; }
.study-plan-overview {
  display: grid;
  grid-template-columns: minmax(195px, .75fr) minmax(0, 1.5fr);
  gap: 18px;
  align-items: center;
  margin-top: 18px;
  padding: 16px 18px;
}
.study-progress [data-testid="study-status"] {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-weight: 600;
}
.study-progress .notice { margin: 9px 0 0; }
.study-plan-overview .paper-summary {
  margin: 0;
  padding: 0 0 0 18px;
  border: 0;
  border-left: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
}
.study-plan-overview .paper-summary p { margin: 0; }
.study-plan-overview .paper-summary__types { margin-top: 7px; }
.study-active .mode-switch { margin: 18px 0 12px; }
.study-active-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 236px;
  align-items: start;
  gap: 18px;
}
.study-active-main { min-width: 0; }
.study-active-aside {
  position: sticky;
  top: calc(var(--topbar-height) + 18px);
  padding: 16px;
}
.study-active-aside .summary h2 { margin: 0; font-size: 14px; }
.study-active-aside .summary ul { margin: 10px 0 16px; }
.study-active-aside .summary li {
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
}
.study-active-aside .actions { margin: 0; }
.study-active-aside [data-testid="append-questions"] { width: 100%; }
.study-active-main .focus-card { padding: 20px; }
.study-active-main .paper-list { margin-top: 0; }
.external-exam-task { max-width: 760px; padding: 18px 0; }
.external-exam-task .eyebrow { margin: 0 0 7px; color: var(--text-tertiary); font-size: 12px; }
.external-exam-task h2 { margin: 0; font-size: 21px; font-weight: 600; }
.external-exam-task__topic { margin: 10px 0; color: var(--text-secondary); }
.external-exam-task__sources { display: flex; flex-wrap: wrap; gap: 7px 16px; margin: 16px 0; color: var(--text-secondary); font-size: 12px; }
.external-exam-task__sources a { color: #416d96; text-decoration: none; }
.external-exam-task__sources a:hover { text-decoration: underline; }
.external-exam-task .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.external-exam-task--paper { padding: 0; }
.external-exam-task--paper h2 { font-size: 18px; }
.study-active > .picker { margin-top: 18px; }
.study-active > .picker h2 { margin-top: 0; font-size: 15px; }
.picker-search { display: block; margin: 10px 0 4px; }
.picker-search input { width: 100%; min-height: 36px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 7px; background: #fff; }
.picker-hint { margin: 5px 0 10px; color: var(--text-tertiary); font-size: 12px; }
.scope-selected-list { max-height: 180px; overflow: auto; margin: 8px 0 12px; padding: 0; list-style: none; }
.scope-selected-list li { display: flex; align-items: center; gap: 6px; padding: 8px 2px; border-bottom: 1px solid #edf0f4; }
.scope-selected-list li > span { flex: 1; min-width: 0; }
.scope-selected-list strong { display: block; font-size: 12px; font-weight: 500; overflow-wrap: anywhere; }
.scope-selected-list small, .selected-kp-path { display: block; margin-top: 3px; color: var(--text-tertiary); font-size: 11px; font-weight: 400; overflow-wrap: anywhere; }
.scope-selected-list button { flex: 0 0 auto; min-height: 32px; padding: 4px 7px; border: 0; background: transparent; color: #527aa1; font-size: 12px; }
.scope-tree-window { max-height: min(390px, 52vh); min-height: 80px; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.scope-tree-window:focus-visible { outline: 2px solid #9bb9dc; outline-offset: 2px; border-radius: 8px; }
.scope-picker-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.scope-picker-footer > span { color: var(--text-tertiary); font-size: 12px; }
.scope-picker-footer button { min-height: 32px; padding: 5px 14px; border-radius: 8px; }
@media (max-width: 960px) {
  .study-setup-layout,
  .study-active-layout,
  .study-plan-overview { grid-template-columns: minmax(0, 1fr); }
  .study-config-panel,
  .study-active-aside { position: static; }
  .study-plan-overview .paper-summary {
    padding: 14px 0 0;
    border-top: 1px solid var(--border);
    border-left: 0;
  }
}
@media (max-width: 600px) {
  .study-select-panel,
  .study-config-panel,
  .study-active-aside { padding: 14px; }
  .study-plan-overview { padding: 14px; }
}

/* 做题优先：辅助信息作为轻量注脚，不再套多层卡片。 */
.study-active { max-width: none; margin: 0; container-type: inline-size; }
.study-active .study-plan-overview { display: block; margin: 6px 0 10px; padding: 0 0 12px; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; }
.study-active .study-progress [data-testid="study-status"] { color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.study-active .study-plan-overview .paper-summary { margin: 5px 0 0; padding: 0; border: 0; }
.study-active .paper-summary__line { color: var(--text-tertiary); font-size: 12px; }
.study-active .paper-summary__line strong { display: none; }
.study-active .paper-summary__types { display: none; }
.study-active .paper-summary .tag { padding: 0; border: 0; background: transparent; color: var(--text-tertiary); font-size: 11px; }
.study-active .mode-switch { display: flex; gap: 20px; margin: 0; padding: 0; border: 0; border-radius: 0; border-bottom: 1px solid var(--border); background: transparent; }
.study-active .mode-switch button { padding: 9px 0; border: 0; border-bottom: 2px solid transparent; border-radius: 0; color: var(--text-tertiary); background: transparent; font-size: 12px; }
.study-active .mode-switch button.active { border-bottom-color: var(--text); color: var(--text); background: transparent; }
.study-active .study-active-layout { display: flex; flex-direction: column; gap: 0; }
.study-active .study-active-main { width: 100%; }
.study-active .study-active-aside { position: static; width: 100%; margin-top: 24px; padding: 18px 0 0; border: 0; border-top: 1px solid var(--border); border-radius: 0; }
.study-active-aside .summary h2 { color: var(--text-secondary); font-size: 12px; font-weight: 500; }
.study-active-aside .summary ul { display: flex; flex-wrap: wrap; gap: 5px 20px; margin: 7px 0 12px; }
.study-active-aside .summary li { padding: 0; border: 0; color: var(--text-tertiary); }
.study-active-aside [data-testid="append-questions"] { width: auto; border-color: var(--border); color: var(--text-secondary); font-weight: 400; }
.study-active-main .paper-list { margin: 0; }
.study-active-main .paper-item { margin: 0; padding: 24px 4px; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; }
.paper-question-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .9fr); align-items: start; gap: 32px; }
.paper-question-main, .paper-answer-pane { min-width: 0; }
.paper-answer-pane { padding: 4px 0 0 22px; border-left: 1px solid var(--border); }
.paper-answer-pane .answer-box { margin-top: 18px; padding: 0; border: 0; background: transparent; overflow-wrap: anywhere; }
.study-active-main .paper-item .stem { margin: 18px 0; font-size: 18px; line-height: 1.8; white-space: pre-wrap; }
.study-active-main .paper-item header .tag { border: 0; background: transparent; color: var(--text-tertiary); }
.study-active-main .paper-item .notice { border: 0; background: transparent; color: var(--text-secondary); font-size: 12px; }
.study-active-main .paper-item header { display: flex; align-items: center; gap: 10px; }
.study-active-main .question-meta { margin-top: 6px; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }
.study-active-main .question-meta summary { width: fit-content; cursor: pointer; }
.study-active-main .question-meta > div { margin: 4px 0 0 12px; }
@container (max-width: 780px) {
  .paper-question-layout { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  .paper-answer-pane { padding: 18px 0 0; border-top: 1px solid var(--border); border-left: 0; }
}
.study-select-panel, .study-config-panel { border: 0; border-radius: 0; padding: 0; }
.study-config-panel { padding-left: 22px; border-left: 1px solid var(--border); }
.study-select-panel .recommend-list { border: 0; border-radius: 0; }
.study-select-panel .recommend-list li { padding-inline: 0; }
@media (max-width: 960px) { .study-config-panel { padding: 18px 0 0; border-left: 0; border-top: 1px solid var(--border); } }

/* 建卷页按一份清晰的任务单排布：先选内容，再定时间，最后生成。 */
.study-setup { width: min(880px, 100%); margin: 0 auto; }
.study-setup-intro { margin: 18px 0 30px; }
.study-setup-intro > span { color: var(--text-tertiary); font-size: 12px; }
.study-setup-intro h2 { margin: 9px 0 0; font-size: clamp(20px, 2.3vw, 25px); font-weight: 610; letter-spacing: -.02em; line-height: 1.35; }
.study-setup-layout { display: block; margin: 0; }
.study-select-panel, .study-config-panel { min-width: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }
.study-config-panel { position: static; margin-top: 27px; padding-top: 23px; border-top: 1px solid var(--border); }
.study-panel-heading { align-items: center; justify-content: space-between; gap: 14px; padding: 0 0 12px; border-bottom: 1px solid var(--border); }
.study-config-panel .study-panel-heading { border-bottom: 0; }
.study-panel-heading h2 { font-size: 15px; font-weight: 620; }
.study-panel-heading p { margin-top: 3px; color: var(--text-tertiary); font-size: 12px; }
.study-panel-heading button { flex: 0 0 auto; min-height: 32px; padding: 5px 10px; border: 1px solid var(--border); border-radius: 8px; color: var(--text-secondary); background: #fff; font-size: 12px; }
.study-panel-heading button:hover:not(:disabled) { border-color: var(--border-strong); background: #f8fafc; }
.study-select-panel .recommend-list { margin: 0; border: 0; border-radius: 0; }
.study-select-panel .recommend-list li { padding: 13px 2px; border-bottom: 1px solid #edf0f4; background: transparent; }
.study-select-panel .recommend-list li:hover { background: transparent; }
.study-select-panel .selected-kp-row { display: flex; align-items: center; gap: 18px; min-height: 55px; }
.selected-kp-row__number { flex: 0 0 22px; color: #95a0ac; font-size: 11px; font-variant-numeric: tabular-nums; }
.study-select-panel .recommend-row { align-items: center; gap: 12px; min-height: 26px; }
.study-select-panel .recommend-row input { flex: 0 0 auto; margin: 0; accent-color: #365e88; }
.study-select-panel .recommend-name { font-size: 14px; font-weight: 560; }
.study-select-panel .recommend-state { margin-left: auto; color: var(--text-tertiary); font-size: 11px; white-space: nowrap; }
.recommend-detail { margin: 2px 0 0 27px; color: var(--text-tertiary); font-size: 11px; }
.recommend-detail summary { width: fit-content; cursor: pointer; }
.recommend-detail p { max-width: 650px; margin: 5px 0 0; line-height: 1.6; }
.study-config-panel .budget { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 2px 0 18px; padding: 0; border: 0; background: transparent; }
.study-config-panel .budget-option { display: flex; align-items: center; justify-content: center; min-height: 52px; margin: 0; padding: 9px 12px; border: 1px solid var(--border); border-radius: 10px; background: #fff; cursor: pointer; }
.study-config-panel .budget-option:last-child { border-bottom: 1px solid var(--border); }
.study-config-panel .budget-option:hover { border-color: #b4c9e2; }
.study-config-panel .budget-option--selected { border-color: #9bb9dc; background: #f7faff; }
.study-config-panel .budget-option:focus-within { outline: 2px solid #9bb9dc; outline-offset: 2px; }
.study-config-panel .budget-option input { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
.budget-option__name { color: var(--text); font-size: 13px; font-weight: 560; }
.study-setup-action { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 15px; border-top: 1px solid var(--border); }
.study-config-panel [data-testid="selected-kp-count"] { margin: 0; color: var(--text-secondary); font-size: 12px; }
.study-config-panel .setup-generate { width: auto; min-width: 176px; min-height: 40px; margin: 0; border-radius: 9px; }
.study-select-panel > .picker { margin: 0 0 20px; padding: 16px 0 17px; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; background: transparent; }
.study-select-panel > .picker h2 { margin: 0; font-size: 15px; font-weight: 610; }
.study-select-panel > .picker > .hint { margin: 5px 0 13px; color: var(--text-tertiary); font-size: 12px; }
.study-select-panel > .picker .recommend-list { margin: 0; border: 0; border-radius: 0; }
.study-select-panel > .picker .recommend-list li { padding: 10px 2px; border-bottom: 1px solid #edf0f4; background: transparent; }
@media (max-width: 600px) {
  .study-setup-intro { margin: 8px 0 24px; }
  .study-panel-heading { align-items: flex-start; }
  .study-panel-heading p { max-width: 210px; }
  .study-config-panel .budget { grid-template-columns: minmax(0, 1fr); gap: 7px; }
  .study-config-panel .budget-option { min-height: 56px; }
  .study-setup-action { align-items: stretch; flex-direction: column; gap: 10px; }
  .study-config-panel .setup-generate { width: 100%; }
}
</style>
