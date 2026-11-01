<script setup lang="ts">
import KnowledgeTreeCanvas from "../components/KnowledgeTreeCanvas.vue";
import { matchingAncestorIds, knowledgePath, toggleKnowledgeBranch } from "../lib/knowledgeNavigation";
import StudyMascot from '../components/StudyMascot.vue';
import { computed, defineAsyncComponent, nextTick, onMounted, onActivated, onDeactivated, shallowRef, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import AppIcon from "../components/AppIcon.vue";
import QuestionSource from "../components/QuestionSource.vue";
import { learningKnowledgeTree } from "../lib/learningKnowledgeTree";
import {
  appendQuestions,
  generateTodayPlan,
  fetchKnowledgeNode,
  fetchKnowledgeTree,
  fetchToday,
  submitNodeSelfAssessment,
} from "../api/study";
import { isTodayActive } from "../types/practice";
import {
  formatTime,
  gradeLabel,
  newIdempotencyKey,
  reasonCodeLabel,
  stateLabel,
  typeLabel,
} from "../lib/labels";
import type {
  KnowledgeNodeDetail,
  KnowledgeNodeView,
  KnowledgeTreeResponse,
  MasteryState,
  NodeSelfAssessmentResponse,
} from "../types/practice";
import { useAsyncTask } from "../composables/useAsyncTask";
import { hidePersonal, readBank, type PersonalQuestion } from "../api/personalQuestions";

type Tab = "overview" | "questions" | "attempts" | "materials";
defineOptions({ name: 'KnowledgePage' });
// These render only after a node is selected; navigation does not wait for
// Markdown parsing or detail projections to be downloaded and initialized.
const MarkdownContent = defineAsyncComponent(() => import('../components/MarkdownContent.vue'));
const KnowledgeCapabilities = defineAsyncComponent(() => import('../components/KnowledgeCapabilities.vue'));
const LearningProgressSummary = defineAsyncComponent(() => import('../components/LearningProgressSummary.vue'));
const PostGraduationPractice = defineAsyncComponent(() => import('../components/PostGraduationPractice.vue'));

const addingQuestionId = ref<string | null>(null);
const questionNotice = ref("");
const questionError = ref("");
async function addOnlineQuestion(questionId: string, kpId: string) {
  if (addingQuestionId.value) return;
  addingQuestionId.value = questionId;
  questionNotice.value = "";
  questionError.value = "";
  try {
    let today = await fetchToday();
    if (!isTodayActive(today)) {
      const nodeDetail = await fetchKnowledgeNode(kpId);
      const needsTransition = nodeDetail.node.graduation_set_binding_status === "legacy_history_unbound"
        && nodeDetail.node.policy_version === 3;
      const confirmation = needsTransition
        ? `今天还没有学习卷。继续后会为“${nodeDetail.node.name}”创建今日学习卷并加入这道题。该节点有历史练习记录，但旧毕业题集无法可靠恢复；历史记录会保留用于查看与学习分析，不计入新版正式毕业题集。确认继续吗？`
        : `今天还没有学习卷。是否创建今日学习卷，并加入“${nodeDetail.node.name}”的这道题？`;
      if (!window.confirm(confirmation)) return;
      today = await generateTodayPlan([kpId], "light", needsTransition ? [kpId] : []);
    }
    if (!isTodayActive(today)) throw new Error("未能创建今日练习，请稍后重试");
    await appendQuestions(today.plan_id, [questionId]);
    questionNotice.value = "已加入今日学习，可在那里作答并查看解析。";
  } catch (error) {
    questionError.value = error instanceof Error ? error.message : "加入今日学习失败";
  } finally {
    addingQuestionId.value = null;
  }
}

// 统一状态（阶段 E）：知识树加载与节点详情都走 `useAsyncTask`。
// 页面侧把 state/error 派生出来，模板绑定与 testid 契约保持原样 ——
// 收敛的是状态来源，不是模板契约。
const treeTask = useAsyncTask<KnowledgeTreeResponse>(null, {
  fallbackMessage: "加载知识树失败",
});
const detailTask = useAsyncTask<KnowledgeNodeDetail>(null, {
  fallbackMessage: "加载知识点详情失败",
});
const { run: runTree } = treeTask;
const { run: runDetail, reset: resetDetail } = detailTask;
const route = useRoute();
const router = useRouter();

const state = computed(() => treeTask.state.value);
const errorCode = computed(() => treeTask.errorCode.value);
const errorMessage = computed(() => treeTask.errorMessage.value);
const roots = shallowRef<KnowledgeNodeView[]>([]);
const treeRefreshing = ref(false);
let treeController: AbortController | null = null;
let detailController: AbortController | null = null;
let treeLoad: Promise<void> | null = null;
let treeSignature = '';

const expanded = ref<Set<string>>(new Set());
const selectedId = ref<string | null>(null);
const treeSearch = ref("");
const rootScope = ref("");
const searchCollapsed = ref(new Set<string>());
const searchExpanded = ref(new Set<string>());
const branchLimits = ref<Record<string, number>>({});
const BRANCH_BATCH = 8;
const treeCanvas = ref<InstanceType<typeof KnowledgeTreeCanvas> | null>(null);
let treeInitialized = false;
let firstActivation = true;
watch(treeSearch, () => {
  searchCollapsed.value = new Set();
  searchExpanded.value = new Set();
  branchLimits.value = {};
});
const searchAncestors = computed(() => matchingAncestorIds(roots.value, treeSearch.value));

function filterTree(nodes: KnowledgeNodeView[], query: string): KnowledgeNodeView[] {
  if (!query) return nodes;
  return nodes.flatMap((node) => {
    const matches = (node.name + " " + node.code).toLocaleLowerCase().includes(query);
    const children = matches ? node.children : filterTree(node.children, query);
    return matches || children.length ? [{ ...node, children }] : [];
  });
}
const visibleRoots = computed(() => filterTree(
  rootScope.value ? roots.value.filter((node) => node.id === rootScope.value) : roots.value,
  treeSearch.value.trim().toLocaleLowerCase(),
));
function branchIsOpen(node: KnowledgeNodeView): boolean {
  return treeSearch.value.trim()
    ? !searchCollapsed.value.has(node.id) && (searchAncestors.value.has(node.id) || searchExpanded.value.has(node.id))
    : expanded.value.has(node.id);
}
const selectedPath = computed(() => selectedId.value ? knowledgePath(roots.value, selectedId.value) : []);
function collapseTree(): void {
  // 收起到初始层级：只保留三个真实根节点，所有后代均由用户逐层展开。
  if (treeSearch.value.trim()) searchCollapsed.value = new Set();
  else expanded.value = new Set();
  searchExpanded.value = new Set();
  branchLimits.value = {};
  if (selectedId.value) closeDetail();
  void nextTick(() => treeCanvas.value?.resetView());
}

function showMore(id: string): void {
  branchLimits.value = { ...branchLimits.value, [id]: (branchLimits.value[id] ?? BRANCH_BATCH) + BRANCH_BATCH };
}
// 详情相关状态统一由 detailTask 派生：模板仍然读 `detail` / `detailLoading` /
// `detailError` 三个名字，但它们的真相只有一个来源。
const detail = computed(() => detailTask.data.value);
const detailLoading = computed(() => detailTask.state.value === "loading");
const detailError = computed(() =>
  detailTask.state.value === "error" ? detailTask.errorMessage.value : null,
);
const tab = ref<Tab>("overview");
async function refreshSelectedDetail(){
  const id=selectedId.value;if(!id)return;
  detailController?.abort();
  const controller = detailController = new AbortController();
  await runDetail(async()=>normalizeDetail(await fetchKnowledgeNode(id,controller.signal)),{keepPreviousData:true});
}
const questionSearch = ref("");
const showHiddenPersonalQuestions = ref(false);
const hiddenPersonalQuestions = ref<PersonalQuestion[]>([]);
const hiddenQuestionsLoading = ref(false);
const hiddenQuestionsError = ref("");
const visibilityBusyId = ref<string | null>(null);
const visibleNodeQuestions = computed(() => {
  const query = questionSearch.value.trim().toLocaleLowerCase();
  return (detail.value?.questions ?? []).filter((question) =>
    !query || question.stem.toLocaleLowerCase().includes(query));
});
async function loadHiddenPersonalQuestions(): Promise<void> {
  if (!selectedId.value || !showHiddenPersonalQuestions.value) return;
  hiddenQuestionsLoading.value = true;
  hiddenQuestionsError.value = "";
  try {
    const result = await readBank("personal", selectedId.value, questionSearch.value, 0, true, 100);
    hiddenPersonalQuestions.value = result.items.filter((question) => question.hidden);
  } catch (error) {
    hiddenQuestionsError.value = error instanceof Error ? error.message : "已隐藏练习暂时无法读取";
  } finally {
    hiddenQuestionsLoading.value = false;
  }
}
async function setPersonalQuestionHidden(question: PersonalQuestion, hidden: boolean): Promise<void> {
  if (visibilityBusyId.value) return;
  visibilityBusyId.value = question.id;
  hiddenQuestionsError.value = "";
  try {
    await hidePersonal(question.id, hidden);
    await refreshSelectedDetail();
    await loadHiddenPersonalQuestions();
  } catch (error) {
    hiddenQuestionsError.value = error instanceof Error ? error.message : (hidden ? "隐藏失败" : "恢复失败");
  } finally {
    visibilityBusyId.value = null;
  }
}
watch(questionSearch, () => { void loadHiddenPersonalQuestions(); });
watch(showHiddenPersonalQuestions, () => { void loadHiddenPersonalQuestions(); });
const detailPanel = ref<HTMLElement | null>(null);

const nodeSubmitting = ref(false);
const nodeNotice = ref<string | null>(null);
const nodeError = ref<string | null>(null);
function flattenLeaves(nodes: KnowledgeNodeView[]): KnowledgeNodeView[] {
  const result: KnowledgeNodeView[] = [];
  const walk = (items: KnowledgeNodeView[]) => {
    for (const node of items) {
      if (node.is_assessable) result.push(node);
      walk(node.children);
    }
  };
  walk(nodes);
  return result;
}

/** 所有可考核叶子，供父节点汇总与未选中时的空状态使用。 */
const allLeaves = computed(() => flattenLeaves(roots.value));

/** 父节点只汇总：由子叶子数量推导，前端不伪造掌握度。 */
const nodeSummaries = computed(() => {
  const summaries = new Map<string, { total: number; done: number; references: number }>();
  const visit = (node: KnowledgeNodeView): { total: number; done: number; references: number } => {
    const result = { total: Number(node.is_assessable), done: Number(node.state === "mastered"), references: Number(node.is_reference_only) };
    for (const child of node.children) {
      const childResult = visit(child);
      result.total += childResult.total;
      result.done += childResult.done;
      result.references += childResult.references;
    }
    summaries.set(node.id, result);
    return result;
  };
  roots.value.forEach(visit);
  return summaries;
});

function summarize(node: KnowledgeNodeView): { total: number; done: number; references: number } {
  return nodeSummaries.value.get(node.id) ?? { total: 0, done: 0, references: 0 };
}


function findLeaf(kpId: string): KnowledgeNodeView | undefined {
  return allLeaves.value.find((leaf) => leaf.id === kpId);
}

function findNodeByCode(nodes: KnowledgeNodeView[], code: string): KnowledgeNodeView | undefined {
  for (const node of nodes) {
    if (node.code === code) return node;
    const found = findNodeByCode(node.children, code);
    if (found) return found;
  }
  return undefined;
}


function load(force = false): Promise<void> {
  if (!force && treeLoad && treeController && !treeController.signal.aborted) return treeLoad;
  treeController?.abort();
  const controller = treeController = new AbortController();
  treeRefreshing.value = roots.value.length > 0;
  const pending = (async () => {
    const data = await runTree(() => fetchKnowledgeTree(controller.signal), {keepPreviousData:true});
    if (!data || controller.signal.aborted) return;
    const signature = JSON.stringify(data.nodes);
    // An unchanged response must not make the canvas fit/re-layout again.
    if (signature !== treeSignature) {
      roots.value = learningKnowledgeTree(data.nodes);
      treeSignature = signature;
    }
    if (!treeInitialized) expanded.value = new Set();
    treeInitialized = true;
  })().finally(() => {
    if (treeController === controller) { treeRefreshing.value = false; treeLoad = null; }
  });
  treeLoad = pending;
  return pending;
}

/**
 * 把后端返回的详情**规范化**成页面可以直接渲染的形状。
 *
 * 为什么要这一层（不是防御性编程洁癖）：页面对详情做了大量零防御假设
 * （`Object.keys(node.required_question_types)`、`detail.questions.length`、
 * `detail.node.gap_items` 的 v-for）。只要响应里少任意一个集合字段，
 * 模板渲染就会抛 `Cannot convert undefined or null to object` ——
 * 这是**未捕获异常**，整块详情直接白屏，用户什么也看不到。
 *
 * e2e 实测抓到的就是这个：mock 少写了几个字段，页面就抛异常白屏，
 * 失败信息是「Cannot convert undefined or null to object」而不是「元素不可见」。
 * 后端字段缺失本该是一处可降级的局部问题，绝不该上升成整页不可用。
 */
function normalizeDetail(raw: KnowledgeNodeDetail): KnowledgeNodeDetail {
  const node = raw?.node ?? ({} as KnowledgeNodeDetail["node"]);
  return {
    ...raw,
    lesson_available: raw?.lesson_available ?? true,
    exam_references: Array.isArray(raw?.exam_references) ? raw.exam_references : [],
    node: {
      ...node,
      gap_items: Array.isArray(node.gap_items) ? node.gap_items : [],
      required_question_types: node.required_question_types ?? {},
      excluded_question_types: Array.isArray(node.excluded_question_types)
        ? node.excluded_question_types
        : [],
      required_skill_tags: Array.isArray(node.required_skill_tags) ? node.required_skill_tags : [],
    },
    questions: Array.isArray(raw?.questions) ? raw.questions : [],
    attempts: Array.isArray(raw?.attempts) ? raw.attempts : [],
  };
}

function toggleExpand(node: KnowledgeNodeView): void {
  if (!node.children.length) return;
  if (treeSearch.value.trim()) {
    if(branchIsOpen(node)) searchCollapsed.value=new Set([...searchCollapsed.value,node.id]);
    else {searchCollapsed.value=new Set([...searchCollapsed.value].filter(id=>id!==node.id));searchExpanded.value=new Set([...searchExpanded.value,node.id]);}
    return;
  }
  expanded.value=toggleKnowledgeBranch(expanded.value,node.id);
}

async function selectNode(node: KnowledgeNodeView, syncUrl = true, expandBranch = true): Promise<void> {
  // 点击节点名称负责选中并逐层展开；同一已选中分支再次点击则收起。
  // 画布标题不再同时发出 toggle 事件，避免一次点击被切换两次而看似无效。
  if (expandBranch && node.children.length) toggleExpand(node);
  if (selectedId.value === node.id) return;
  if (syncUrl) void router.replace({ path: "/knowledge", query: { node: node.code } });
  const kpId = node.id;
  selectedId.value = kpId;
  questionSearch.value = "";
  showHiddenPersonalQuestions.value = false;
  hiddenPersonalQuestions.value = [];
  hiddenQuestionsError.value = "";
  await nextTick();
  if (window.matchMedia('(max-width: 900px)').matches) detailPanel.value?.scrollIntoView({ behavior: "smooth", block: "start" });
  tab.value = "overview";
  nodeNotice.value = null;
  nodeError.value = null;
  resetDetail();
  detailController?.abort();
  const controller = detailController = new AbortController();
  const data = await runDetail(async () => normalizeDetail(await fetchKnowledgeNode(kpId,controller.signal)));
  // 过期/被取消的选择：结果已经不重要，直接丢弃。
  if (selectedId.value !== kpId) return;
  if (data) {
    // 等真实详情完成布局再定位。加载占位时滚动会被短页面高度截住，
    // 在手机上留下标题被底部导航遮住的半截视图。
    if(window.matchMedia('(max-width: 900px)').matches){await nextTick();detailPanel.value?.scrollIntoView({behavior:'auto',block:'start'});}
    return;
  }
  if (detailTask.errorCode.value === "knowledge_point_not_found") {
    // 规格 2.5：节点被删 → 知识树刷新，详情区回到空态。
    // 不能停在一个指向已删节点的详情上。
    selectedId.value = null;
    await load();
  }
}

async function nodeAssess(grade: "mastered" | "partial" | "not_mastered"): Promise<void> {
  if (!selectedId.value) return;
  const kpId = selectedId.value;
  nodeSubmitting.value = true;
  nodeError.value = null;
  nodeNotice.value = null;
  try {
    const result: NodeSelfAssessmentResponse = await submitNodeSelfAssessment(
      kpId,
      grade,
      newIdempotencyKey(`node-${kpId}`),
    );
    // 先刷新树与详情（selectNode 会清空反馈），再写入反馈，否则用户看不到结果。
    await load(true);
    await refreshSelectedDetail();

    // 基础确认数由后端给出：绝不在前端假装用户做了两题。
    const credit =
      result.reason_code === "self_feedback_only" ? "信心已记录，不增加客观确认" : result.manual_credit_count > 0 ? `基础确认 +${result.manual_credit_count}` : "基础确认为 0";
    nodeNotice.value =
      `${reasonCodeLabel(result.reason_code)}；${credit}；` +
      `有效确认 ${result.effective_confirmation_count}；当前状态 ${stateLabel(result.state)}`;
  } catch (error) {
    if (!(error instanceof ApiError)) {
      nodeError.value = "整体自评失败";
      return;
    }
    // 规格 2.5：只按 code 决定行为。逐项都在表里，没列的走兜底。
    switch (error.code) {
      case "node_not_assessable":
        // 父节点不可考核（正常情况下页面根本不显示这些按钮，只有直接调接口才会走到）。
        nodeError.value = "这个节点只是章节汇总，不能整体自评。请选择它下面的叶子节点。";
        return;
      case "knowledge_point_not_found":
        nodeError.value = "这个知识点已经不存在了，已刷新知识树。";
        selectedId.value = null;
        resetDetail();
        await load();
        return;
      case "kp_state_not_found":
        nodeError.value = "缺少掌握度投影行，请先运行 python scripts\\seed.py。";
        return;
      default:
        nodeError.value = `${error.message}（${error.code ?? "未知错误"}）`;
    }
  } finally {
    nodeSubmitting.value = false;
  }
}

const stateTone = (value: MasteryState | null | string): string => `tone tone--${value ?? "aggregate"}`;

function closeDetail(): void {
  detailController?.abort();
  selectedId.value = null;
  resetDetail();
  void router.replace({ path: '/knowledge', query: { ...route.query, node: undefined } });
}

onActivated(async()=>{
  if (firstActivation) { firstActivation = false; return; } // mounted owns the initial request
  const sameSelection = selectedPath.value.at(-1)?.code === route.query.node;
  await Promise.all([load(), sameSelection ? refreshSelectedDetail() : restoreRouteSelection()]);
  await restoreRouteSelection();
});
onDeactivated(()=>{treeController?.abort();detailController?.abort();});
async function restoreRouteSelection(){
  if (route.path !== '/knowledge') return;
  const code = typeof route.query.node === "string" ? route.query.node : null;
  if (!code) {if(selectedId.value){selectedId.value=null;resetDetail();}return;}
  const node = findNodeByCode(roots.value, code);
  if (!node) return;
  if(selectedId.value===node.id)return;
  const path=knowledgePath(roots.value,node.id);
  if(rootScope.value && rootScope.value!==path[0]?.id)rootScope.value=path[0]?.id??'';
  // 深链接展开祖先路径，而不是把整棵树过滤成孤立的一条搜索结果。
  expanded.value = new Set([...expanded.value, ...path.slice(0, -1).map(parent => parent.id)]);
  await selectNode(node, false, false);
  if (node.is_assessable && route.query.tab === "questions") tab.value = "questions";
}
onMounted(async () => {await load();await restoreRouteSelection();});
watch(()=>route.query.node,()=>{if(route.path==='/knowledge'&&treeInitialized)void restoreRouteSelection();});
watch(rootScope,(scope)=>{if(scope && selectedPath.value.length && selectedPath.value[0].id!==scope)closeDetail();});
</script>

<template>
  <section class="page page--knowledge">
    <header class="knowledge-page-heading">
      <div class="knowledge-heading-copy">
        <p class="knowledge-page-kicker">知识，和你一起生长</p>
        <h2>把知识，一片一片连起来。</h2>
        <p>沿着奶蛙脚趾连接的分支，逐层找到今天要学的知识点。</p>
      </div>
      <div class="tree-toolbar">
        <input v-model="treeSearch" type="search" aria-label="搜索知识点名称或编号" placeholder="搜索知识点或章节" data-testid="knowledge-search" />
        <select v-if="roots.length > 1" v-model="rootScope" aria-label="知识树学科范围"><option value="">全部学科</option><option v-for="root in roots" :key="root.id" :value="root.id">{{ root.name }}</option></select>
        <button v-if="treeSearch" type="button" @click="treeSearch = ''">清除搜索</button>
        <button type="button" class="tree-collapse" @click="collapseTree">收起分支</button>
      </div>
    </header>

    <p v-if="state === 'loading' && !roots.length" class="state state--loading" data-testid="knowledge-loading">
      正在加载知识树…
    </p>
    <div v-if="state === 'error'" class="state state--error" data-testid="knowledge-error">
      <p>{{ errorMessage }}</p>
      <p v-if="errorCode" class="state__code">错误码：{{ errorCode }}</p>
      <button type="button" @click="load()">重试</button>
    </div>

    <p v-if="treeRefreshing" class="state" role="status">正在更新知识树学习状态…</p>
    <div v-if="roots.length || state === 'success'" class="knowledge-layout" :class="{ 'knowledge-layout--inspecting': selectedId }">
      <section class="tree" data-testid="knowledge-tree" aria-label="知识树">
        <div class="tree-heading"><div><strong>知识结构</strong><span>{{ allLeaves.length }} 个学习知识点</span></div><span>脚趾连分支 · 点击节点查看详情</span></div>
        <p v-if="!roots.length" class="state state--empty" data-testid="knowledge-empty">还没有可显示的知识点。</p>
        <p v-else-if="!visibleRoots.length" class="state state--empty" data-testid="knowledge-search-empty">没有找到匹配的知识点，试试其他名称或编号。</p>
        <KnowledgeTreeCanvas
          v-else
          ref="treeCanvas"
          :nodes="visibleRoots"
          :selected-id="selectedId"
          :is-open="branchIsOpen"
          :limits="branchLimits"
          :batch-size="BRANCH_BATCH"
          @select="selectNode($event)"
          @toggle="toggleExpand"
          @more="showMore"
        />
      </section>

      <div v-if="selectedId" ref="detailPanel" class="detail" aria-label="知识节点详情">
        <button type="button" class="knowledge-detail-close" aria-label="关闭知识节点详情" @click="closeDetail">关闭详情 <span aria-hidden="true">×</span></button>

        <p v-if="detailLoading" class="state state--loading" data-testid="detail-loading">
          正在加载知识点详情…
        </p>
        <p v-else-if="detailError" class="state state--error">{{ detailError }}</p>

        <div v-else-if="detail" data-testid="knowledge-detail">
          <header class="knowledge-detail-heading">
            <div>
              <p class="knowledge-breadcrumb" data-testid="knowledge-breadcrumb">{{ selectedPath.map((node) => node.name).join(' / ') }}</p>
              <h2 data-testid="detail-title">{{ detail.node.name }}</h2>
            </div>
          </header>
            <p v-if="detail.node.graduation_set_binding_status === 'legacy_history_unbound' && detail.node.policy_version === 3" class="notice" data-testid="legacy-set-transition-notice">
              该节点保留有历史练习记录，但无法可靠恢复旧毕业题集。历史记录仅用于查看与学习分析；开始新版正式考核时会单独征求确认。
            </p>
          <p v-if="!detail.node.is_assessable && detail.node.post_graduation_review_count">下属 {{detail.node.post_graduation_review_count}} 个知识点建议复习。</p>
          <PostGraduationPractice v-if="detail.node.post_graduation?.applicable" :practice="detail.node.post_graduation" :node-id="detail.node.id" />
          <div v-if="detail.node.is_assessable" class="knowledge-assistant-entry" data-testid="knowledge-assistant-entry">
            <StudyMascot pose="teach" />
            <div><strong>围绕这个知识点，和奶蛙一起学</strong><span>讲解、安排练习或生成新题；计划与加入今日学习仍由你确认。</span></div>
            <RouterLink :key="detail.node.id" :to="{path:'/chat',query:{knowledge_node_id:detail.node.id,clear_context:'1'}}" data-testid="knowledge-assistant-link">询问奶蛙 ↗</RouterLink>
          </div>
          <LearningProgressSummary v-if="detail.capability_profile?.learning_progress && !detail.node.post_graduation?.applicable"
            :progress="detail.capability_profile.learning_progress"
            :lesson-to="detail.lesson_available ? '/knowledge/' + encodeURIComponent(detail.node.code) + '/lesson' : undefined" />
          <p v-if="detail.capability_profile?.graduation_progress?.configured" class="graduation-progress-summary" data-testid="graduation-progress-summary">
            毕业题目：真正完成 {{ detail.capability_profile.graduation_progress.completed_question_count }} / {{ detail.capability_profile.graduation_progress.required_question_count }} 道
            <span v-if="detail.capability_profile.graduation_progress.graduated">· 已毕业</span>
          </p>
          <p v-else-if="detail.capability_profile?.graduation_progress" class="graduation-progress-summary" data-testid="graduation-progress-summary">
            毕业题目集合尚未配置；题目进度不会因空集合自动毕业。
          </p>

          <nav class="mode-switch">
            <button type="button" :class="{ active: tab === 'overview' }" data-testid="tab-overview" @click="tab = 'overview'">概览</button>
            <button v-if="detail.node.is_assessable && (!detail.node.is_reference_only || detail.questions.length)" type="button" :class="{ active: tab === 'questions' }" data-testid="tab-questions" @click="tab = 'questions'">题库 <span v-if="detail.questions.length">{{ detail.questions.length }}</span></button>
            <button v-if="detail.node.is_assessable" type="button" :class="{ active: tab === 'attempts' }" data-testid="tab-attempts" @click="tab = 'attempts'">练习记录</button>
            <button v-if="detail.node.is_assessable" type="button" :class="{ active: tab === 'materials' }" data-testid="tab-materials" @click="tab = 'materials'">关联资料</button>
          </nav>

          <!--
            概览：父节点只做汇总、叶子才是可考核单元（第 17 篇规格 2.2 的表格）。
            两个 testid 按节点类型二选一，验收脚本据此断言「父节点不显示可自评内容」。
          -->
          <section
            v-if="tab === 'overview'"
            class="card"
            :data-testid="detail.node.is_assessable ? 'knowledge-leaf-overview' : 'knowledge-parent-summary'"
          >
            <RouterLink
              v-if="detail.lesson_available"
              class="knowledge-lesson-link"
              data-testid="knowledge-lesson-link"
              :to="'/knowledge/' + encodeURIComponent(detail.node.code) + '/lesson'"
            >
              <AppIcon name="materials" :size="19" />
              <span class="knowledge-lesson-link__body">
                <strong>{{ detail.node.name }} · {{ detail.node.is_assessable ? "系统讲解" : "章节导读" }}</strong>
                <small>在独立阅读页查看完整讲解与例题分析</small>
              </span>
              <span aria-hidden="true">→</span>
            </RouterLink>
            <p v-if="detail.node.summary"><strong>知识摘要：</strong>{{ detail.node.summary }}</p>
            <p v-if="detail.node.learning_goal"><strong>学习目标：</strong>{{ detail.node.learning_goal }}</p>


            <KnowledgeCapabilities v-if="detail.capability_profile" :profile="detail.capability_profile" />

            <p v-if="detail.node.next_step && !detail.capability_profile?.learning_progress" class="notice" data-testid="next-step">
              <strong>原评价建议：</strong>{{ detail.node.next_step }}
            </p>
            <details v-if="detail.node.is_assessable" class="knowledge-advanced" data-testid="knowledge-advanced">
              <summary>查看毕业进度与考核要求</summary>
              <p class="state" data-testid="detail-state">原评价状态：{{ stateLabel(detail.node.state) }}</p>
              <p class="hint" data-testid="assessment-basis">此处保留原评价结果；当前严格确认按有效收据核验，与上方学习进展分开。自评与参考比对不增加严格确认。</p>
            <!-- 毕业进度：逐项来自后端 gap_items，前端不自己算毕业条件 -->
            <h3 class="section-title">毕业进度</h3>
            <template v-if="detail.capability_profile?.graduation_progress">
              <p class="hint" data-testid="graduation-evidence-boundary">毕业只看本节点冻结题目是否逐题真正完成。错题复习、间隔安排和变式训练由今日学习与奶蛙负责，不额外变成毕业配额。</p>
              <p v-if="!detail.capability_profile.graduation_progress.configured" class="notice" data-testid="graduation-set-unconfigured">这个知识点尚未配置可毕业的正式题目集合；不会因为题集为空而自动毕业。</p>
              <p v-else data-testid="graduation-set-progress">已真正完成 {{ detail.capability_profile.graduation_progress.completed_question_count }} / {{ detail.capability_profile.graduation_progress.required_question_count }} 道规定题目<span v-if="detail.capability_profile.graduation_progress.graduated"> · 已毕业</span></p>
              <ul v-if="(detail.capability_profile.graduation_progress.questions ?? []).length" class="gap-list" data-testid="graduation-set-items">
                <li v-for="item in detail.capability_profile.graduation_progress.questions ?? []" :key="item.question_id" class="gap-item">
                  <span class="gap-item__label">规定题目 {{ item.ordinal }}</span>
                  <span class="gap-item__value">{{ item.status === 'COMPLETED' ? '已真正完成' : item.status === 'IN_PROGRESS' ? '学习中，待独立完成' : '未开始' }}</span>
                </li>
              </ul>
              <p v-if="detail.capability_profile.graduation_progress.graduated_at" class="hint" data-testid="graduation-set-date">毕业记录：{{ formatTime(detail.capability_profile.graduation_progress.graduated_at) }}</p>
            </template>
            <template v-else>
            <p class="hint" data-testid="graduation-evidence-boundary">以下是知识点的考核要求。练习按题库答案核对；自行对照与 AI 辅助审阅只作学习反馈。</p>
            <p v-if="Object.keys(detail.node.required_question_types ?? {}).some(type => !['single_choice', 'fill_blank', 'calculation'].includes(type))" class="hint" data-testid="graduation-process-gap">证明、讨论等过程题需要检查推导或论证，最终答案不能单独代表掌握。</p>
            <ul class="gap-list" data-testid="gap-list">
              <li
                v-for="gap in detail.node.gap_items"
                :key="gap.key"
                class="gap-item"
                :class="{ 'gap-item--done': gap.satisfied }"
                :data-testid="`gap-${gap.key}`"
              >
                <span class="gap-item__mark">{{ gap.satisfied ? "✓" : "○" }}</span>
                <span class="gap-item__label">{{ gap.label }}</span>
                <span class="gap-item__value">{{ gap.current }} / {{ gap.required }}</span>
              </li>
            </ul>

            <!-- 该知识点自己的策略：让用户看懂「为什么要求这些」 -->
            <h3 class="section-title">该知识点的考核要求</h3>
            <dl class="facts">
              <dt>有效确认数</dt>
              <dd data-testid="effective-count">{{ detail.node.effective_confirmation_count }}</dd>
              <dt>历史基础确认</dt>
              <dd data-testid="manual-credit">{{ detail.node.manual_credit_count }}</dd>
              <dt>必考题型</dt>
              <dd data-testid="required-types">
                <span
                  v-for="(count, type) in detail.node.required_question_types ?? {}"
                  :key="type"
                  class="tag"
                >
                  {{ typeLabel(String(type)) }} ≥ {{ count }}
                </span>
                <span
                  v-if="Object.keys(detail.node.required_question_types ?? {}).length === 0"
                  class="hint"
                >未单独配置题型要求</span>
              </dd>
              <dt>不考题型</dt>
              <dd data-testid="excluded-types">
                <span
                  v-for="type in detail.node.excluded_question_types ?? []"
                  :key="type"
                  class="tag tag--muted"
                >{{ typeLabel(type) }}</span>
                <span v-if="(detail.node.excluded_question_types ?? []).length === 0" class="hint">无</span>
              </dd>
              <dt>必考考法</dt>
              <dd data-testid="required-tags">
                <span
                  v-for="tag in detail.node.required_skill_tags ?? []"
                  :key="tag"
                  class="tag tag--muted"
                >{{ tag }}</span>
                <span v-if="(detail.node.required_skill_tags ?? []).length === 0" class="hint">无</span>
              </dd>
              <dt>首尾确认跨度</dt>
              <dd data-testid="day-span">
                {{ detail.node.day_span === null ? "—" : `${detail.node.day_span} 天` }}
                （{{ detail.node.first_confirmed_on ?? "—" }} → {{ detail.node.last_confirmed_on ?? "—" }}）
              </dd>
              <template v-if="!detail.node.is_reference_only">
                <dt>已有真实变式题确认</dt>
                <dd data-testid="has-variant">{{ detail.node.has_real_variant ? "是" : "否" }}</dd>
              </template>
              <dt>下次复习</dt>
              <dd>{{ formatTime(detail.node.next_review_at) }}</dd>
            </dl>
            </template>
            </details>

            <!-- 叶子整体自评：只有 is_assessable 叶子才有这一组按钮 -->
            <div v-if="detail.node.is_assessable" class="actions actions--grades" data-testid="node-assessment">
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-mastered" @click="nodeAssess('mastered')">
                自述熟悉
              </button>
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-partial" @click="nodeAssess('partial')">
                自述不太熟悉
              </button>
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-not-mastered" @click="nodeAssess('not_mastered')">
                自述不熟悉
              </button>
            </div>
            <p v-if="detail.node.is_assessable" class="hint">自述仅作辅助反馈，不增加毕业确认；旧自评历史保留。</p>
            <p v-if="nodeNotice" class="notice" data-testid="node-notice">{{ nodeNotice }}</p>
            <p v-if="nodeError" class="form-error">{{ nodeError }}</p>
          </section>

          <!-- 题库：只显示题干，不显示答案 -->
          <section v-else-if="tab === 'questions'" class="card" data-testid="question-bank">
            <div class="question-bank-heading">
              <div>
                <h3>{{ detail.node.name }} · 练习题</h3>
                <p class="hint">公共正式题与 AI 练习统一按知识点展示；个人 AI 练习不计入正式毕业。</p>
              </div>
              <form class="question-search" role="search" @submit.prevent>
                <label for="node-question-search">搜索本知识点题目</label>
                <input id="node-question-search" v-model="questionSearch" type="search" maxlength="100" placeholder="输入题干关键词" />
              </form>
            </div>
            <label class="hidden-question-toggle"><input v-model="showHiddenPersonalQuestions" type="checkbox" /> 显示已隐藏的 AI 练习</label>
            <p v-if="!visibleNodeQuestions.length && !showHiddenPersonalQuestions" class="state state--empty">{{ questionSearch ? '没有找到匹配的题目。' : '该知识点还没有题目。' }}</p>
            <p v-if="showHiddenPersonalQuestions && hiddenQuestionsLoading" role="status" class="state state--loading">正在读取已隐藏的 AI 练习…</p>
            <p v-if="hiddenQuestionsError" role="alert" class="form-error">{{ hiddenQuestionsError }}</p>
            <ul v-if="visibleNodeQuestions.length">
              <li v-for="question in visibleNodeQuestions" :key="question.id" class="pool-item" :data-testid="question.bank_scope === 'personal' ? 'personal-node-question' : 'public-node-question'">
                <QuestionSource :source="question.question_source" :trust="question.trust" :is-variant="question.is_variant" />
                <span v-if="question.bank_scope === 'personal'" class="tag tag--muted">个人练习 · 不计毕业</span>
                <MarkdownContent :text="question.stem" />
                <ol v-if="question.options" class="question-options">
                  <li v-for="(text, key) in question.options" :key="key"><span>{{ key }}.</span> <MarkdownContent :text="text" /></li>
                </ol>
                <span class="tag tag--muted">{{ typeLabel(question.question_type) }}</span>
                <span class="tag tag--muted">{{ question.difficulty }}</span>
                <span v-if="question.is_variant" class="tag">变式题</span>
                <button type="button" :disabled="addingQuestionId !== null || !question.trust.practice_eligible" @click="addOnlineQuestion(question.id, question.kp_id)">{{ addingQuestionId === question.id ? '正在加入…' : '加入今日学习' }}</button>
                <button v-if="question.bank_scope === 'personal'" type="button" class="quiet-action" :disabled="visibilityBusyId !== null" @click="setPersonalQuestionHidden({id:question.id,kp_id:question.kp_id,bank_scope:'personal',hidden:false,question_type:question.question_type,difficulty:question.difficulty,stem:question.stem,options:question.options ?? null,practice_eligible:question.trust.practice_eligible}, true)">{{ visibilityBusyId === question.id ? '处理中…' : '隐藏' }}</button>
              </li>
            </ul>
            <template v-if="showHiddenPersonalQuestions">
              <h4>已隐藏的 AI 练习</h4>
              <p v-if="!hiddenQuestionsLoading && !hiddenPersonalQuestions.length" class="state state--empty">{{ questionSearch ? '没有匹配的已隐藏练习。' : '没有已隐藏的 AI 练习。' }}</p>
              <ul v-if="hiddenPersonalQuestions.length">
                <li v-for="question in hiddenPersonalQuestions" :key="question.id" class="pool-item" data-testid="hidden-personal-question">
                  <span class="tag tag--muted">AI练习题 · 个人练习，不计毕业</span>
                  <MarkdownContent :text="question.stem" />
                  <span class="tag tag--muted">{{ typeLabel(question.question_type) }}</span>
                  <span class="tag tag--muted">{{ question.difficulty }}</span>
                  <button type="button" :disabled="visibilityBusyId !== null" @click="setPersonalQuestionHidden(question, false)">{{ visibilityBusyId === question.id ? '处理中…' : '恢复显示' }}</button>
                </li>
              </ul>
            </template>
            <p class="hint">题库不显示答案；答案详解只在答题页查看答案时读取。</p>
            <p v-if="questionNotice" role="status" class="notice">{{ questionNotice }}</p>
            <p v-if="questionError" role="alert" class="form-error">{{ questionError }}</p>
          </section>

          <!-- 练习记录 -->
          <section v-else-if="tab === 'attempts'" class="card" data-testid="attempt-history">
            <p v-if="detail.attempts.length === 0" class="state state--empty">还没有练习记录。</p>
            <ul v-else>
              <li v-for="attempt in detail.attempts" :key="attempt.id" class="attempt-item">
                <p>{{ attempt.question_stem }}</p>
                <span class="tag" :class="stateTone(attempt.result_state)">{{ attempt.self_grade ? gradeLabel(attempt.self_grade) : attempt.objective_result === 'right' ? '最终答案正确' : attempt.objective_result === 'wrong' ? '最终答案不正确' : '未自动判定' }}</span>
                <span v-if="attempt.grading_evidence?.assisted" class="tag tag--muted">提交前已查看解析</span>
                <span class="tag tag--muted">{{ formatTime(attempt.submitted_at) }}</span>
                <span class="tag tag--muted">{{ reasonCodeLabel(attempt.reason_code) }}</span>
                <p v-if="attempt.raw_answer" class="hint">我的作答：{{ attempt.raw_answer }}</p>
              </li>
            </ul>
          </section>


          <!-- 关联资料 -->
          <section v-else class="card" data-testid="panel-materials">
            <p class="state state--empty">
              系统讲解可从「概览」打开；这里暂不自动匹配上传资料，避免把不相关的内容误标为关联。
            </p>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>


<style scoped>
.page--knowledge { width: min(1180px, 100%); }
.knowledge-layout { grid-template-columns: minmax(300px, .88fr) minmax(0, 1.35fr); gap: 32px; }
.tree { padding: 0; border: 0; border-radius: 0; }
.tree::before { display: none; }
.tree-heading { display: flex; justify-content: space-between; align-items: baseline; padding: 0 4px 12px; border-bottom: 1px solid var(--border); }
.tree-heading strong { font-size: 13px; font-weight: 600; }
.tree-heading span { color: var(--text-tertiary); font-size: 11px; }
.tree > .tree-root { padding: 8px 0 0; }
.tree-entry { position: relative; padding-left: calc(var(--tree-depth) * 21px); }
.tree-entry:not([data-depth="0"])::before { content: ""; position: absolute; top: 0; bottom: 0; left: calc(var(--tree-depth) * 21px - 11px); border-left: 1px solid #dadbdd; }
.tree-entry:not([data-depth="0"])::after { content: ""; position: absolute; top: 21px; left: calc(var(--tree-depth) * 21px - 11px); width: 11px; border-top: 1px solid #dadbdd; }
.tree-row { position: relative; z-index: 1; min-height: 43px; gap: 3px; padding: 2px 0; }
.tree-toggle { flex-basis: 22px; width: 22px; min-height: 22px; color: var(--text-tertiary); font-size: 12px; }
.tree-toggle--empty { position: relative; }
.tree-toggle--empty::after { content: ""; display: block; width: 5px; height: 5px; border-radius: 50%; background: #c2c4c6; }
.tree-node { flex: 1; min-height: 32px; padding: 4px 7px; font-size: 13px; }
.tree-node--branch { font-weight: 600; }
.tree-node--selected { background: #f0f1f2 !important; }
.tree-progress, .tree-leaf-state { flex: 0 0 auto; margin-left: 4px; color: var(--text-tertiary); font-size: 11px; white-space: nowrap; }
.tree-leaf-state { display: inline-flex; align-items: center; gap: 5px; }
.tree-leaf-state--reference { color: #617d6a; }
.tree-leaf-dot { width: 6px; height: 6px; border-radius: 50%; background: #b9bbbe; }
.tree-leaf-state.tone--mastered .tree-leaf-dot { background: var(--success); }
.tree-leaf-state.tone--consolidating .tree-leaf-dot { background: var(--warning); }
.question-bank-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: end; gap: 12px; margin-bottom: 12px; }
.question-bank-heading h3 { margin: 0 0 4px; }
.question-bank-heading p { margin: 0; }
.question-search { display: grid; gap: 4px; min-width: min(260px, 100%); }
.question-search input { min-height: 36px; }
.hidden-question-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 6px 0 12px; }
.quiet-action { margin-left: 6px; }
.tree-leaf-state.tone--stuck .tree-leaf-dot { background: var(--danger); }
.detail { min-height: 270px; padding: 0; border: 0; border-radius: 0; }
.detail > [data-testid="knowledge-detail"] > h2 { font-size: 20px; }
.detail [data-testid="detail-state"] { display: inline-block; margin: 5px 0 12px; padding: 0; border: 0; background: transparent; color: var(--text-secondary); font-size: 12px; }
.detail .mode-switch { display: flex; gap: 18px; margin: 8px 0 0; padding: 0; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; background: transparent; }
.detail .mode-switch button { padding: 9px 0; border: 0; border-bottom: 2px solid transparent; border-radius: 0; color: var(--text-tertiary); background: transparent; font-size: 12px; }
.detail .mode-switch button.active { border-bottom-color: var(--text); color: var(--text); background: transparent; }
.detail .card { padding: 18px 0 0; border: 0; }
.detail .card > p:first-child { margin-top: 0; }
.detail .card .notice { padding: 10px 0; border: 0; background: transparent; color: var(--text-secondary); }
.knowledge-advanced { margin-top: 22px; padding-top: 12px; border-top: 1px solid var(--border); }
.knowledge-advanced summary { width: fit-content; color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.knowledge-advanced .section-title { color: var(--text-secondary); font-size: 12px; }
.knowledge-advanced .gap-list { border: 0; border-radius: 0; }
.knowledge-advanced .gap-item { padding-inline: 0; }
.knowledge-advanced .facts { padding-top: 5px; font-size: 12px; }
.detail [data-testid="node-assessment"] { margin-top: 23px; padding-top: 16px; border-top: 1px solid var(--border); }
.detail [data-testid="node-assessment"] button { border-color: transparent; color: var(--text-secondary); background: #f5f5f5; font-weight: 400; }
.detail [data-testid="node-assessment"] button:hover:not(:disabled) { background: #ebebeb; }
.detail [data-testid="knowledge-leaf-overview"] > .hint { margin-top: 6px; }
.detail .pool-item, .detail .attempt-item { border-bottom: 1px solid var(--border); }
@media (max-width: 900px) { .knowledge-layout { gap: 18px; } }
@media (max-width: 740px) { .knowledge-layout { grid-template-columns: minmax(0, 1fr); } .tree { max-height: 42vh; } .detail { padding: 0; } }
@media (max-width: 480px) { .tree-progress { font-size: 10px; } .tree-row { min-height: 40px; } .detail .mode-switch { gap: 12px; } }
/* 树是页面主体：横向分叉画布，详情置于树下。 */
.page--knowledge { width: min(1280px, 100%); }
.knowledge-layout { display: block; margin-top: 14px; }
.tree { position: static; top: auto; width: 100%; max-height: none; padding: 0; overflow: visible; border: 0; }
.tree-heading { padding: 0 0 12px; }
.tree-viewport { min-height: 480px; max-height: min(68vh, 720px); overflow: auto; overscroll-behavior: contain; border-bottom: 1px solid var(--border); }
.tree-graph { position: relative; min-height: 420px; }
.tree-edges { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
.tree-edges path { fill: none; stroke: #b9cabc; stroke-width: 2; stroke-linecap: round; }
.tree-entry { position: absolute; z-index: 1; width: 190px; padding: 9px 10px 8px; transform: translateY(-50%); border: 1px solid #dce5de; border-radius: 12px; background: #fff; box-shadow: 0 2px 8px rgba(35, 60, 40, .04); }
.tree-entry::before, .tree-entry::after { display: none !important; }
.tree-entry--root { border-color: #bacfbe; background: #f4f8f4; }
.tree-entry:focus-within { border-color: #84a68b; }
.tree-row { min-height: 28px; gap: 5px; padding: 0; }
.tree-toggle { flex: 0 0 22px; width: 22px; min-height: 22px; background: transparent; }
.tree-toggle--empty::after { width: 6px; height: 6px; background: #8aa991; }
.tree-node { flex: 1; min-height: 27px; padding: 2px 3px; color: #253b2a; font-size: 12px; line-height: 1.35; }
.tree-node--selected { background: #e4efe5 !important; }
.tree-progress, .tree-leaf-state { margin: 2px 0 0 27px; font-size: 10px; }
.tree-leaf-state { display: flex; }
.detail { width: min(920px, 100%); min-height: 0; margin: 26px auto 0; padding: 0 0 30px; scroll-margin-top: 72px; }
.detail > .state--empty { border: 0; padding: 10px 0; background: transparent; }
@media (max-width: 740px) {
  .tree { max-height: none; }
  .tree-viewport { min-height: 380px; max-height: 55vh; }
  .detail { margin-top: 20px; }
}
.tree-viewport { border: 1px solid var(--border); border-radius: 14px; }
.knowledge-lesson-link { display: flex; align-items: center; gap: 12px; padding: 14px 16px; margin-bottom: 18px; border: 1px solid var(--border); border-radius: 12px; color: var(--text); text-decoration: none; }
.knowledge-lesson-link:hover, .knowledge-lesson-link:focus-visible { border-color: #a9c8e6; background: #f7fbff; }
.knowledge-lesson-link__body { display: grid; flex: 1; gap: 3px; }
.knowledge-lesson-link__body strong { font-size: 14px; font-weight: 600; }
.knowledge-lesson-link__body small { color: var(--text-secondary); font-size: 12px; }
.tree-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.tree-heading > div { display: flex; align-items: baseline; gap: 12px; }
.tree-heading span { color: var(--text-tertiary); font-size: 12px; }
.tree-collapse, .tree-toolbar button { padding: 5px 9px; border: 0; border-radius: 8px; background: transparent; color: var(--text-secondary); font-size: 12px; }
.tree-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.tree-toolbar input { width: min(340px, 100%); min-width: 0; min-height: 36px; padding: 7px 12px; border: 1px solid #e5eaf0; border-radius: 10px; background: #fafcfe; font-size: 13px; }
.tree-toolbar select { width: auto; max-width: 180px; min-height: 36px; padding: 5px 10px; border: 1px solid #e5eaf0; border-radius: 10px; background: #fff; font-size: 12px; }
.tree-viewport { min-height: 400px; background: radial-gradient(#e9edf1 .7px, transparent .7px) 0 0 / 18px 18px; border-color: #e6ebef; }
.tree-entry { border-color: #e1e9e6; box-shadow: 0 2px 7px rgb(36 57 48 / 3%); }
.tree-entry--more { padding: 5px 10px; border: 0; background: #f5f8f7; box-shadow: none; }
.tree-more { display: flex; align-items: center; justify-content: space-between; gap: 6px; width: 100%; padding: 8px 0; border: 0; background: transparent; color: #456657; font-size: 12px; }
.tree-more small { color: #809187; font-size: 10px; }
.exam-reference-note { margin: -2px 0 10px; }
.exam-reference-count { display: inline-flex; min-width: 18px; justify-content: center; margin-left: 3px; padding: 1px 5px; border-radius: 999px; background: #f0f3f6; color: var(--text-secondary); font-size: 10px; }
.exam-reference-panel > .hint:first-child { margin-top: 0; }
.exam-year { border-bottom: 1px solid var(--border); }
.exam-year > summary { padding: 13px 0; color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; }
.exam-reference-list { margin: 0; padding: 0; list-style: none; }
.exam-reference-item { padding: 12px 0; border-top: 1px solid var(--border); }
.exam-reference-item__heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; font-size: 13px; }
.exam-reference-item__heading > span { color: var(--text-secondary); }
.exam-reference-item__sources { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 7px; font-size: 11px; }
.exam-reference-item__sources a { color: #416d96; text-decoration: none; }
.exam-reference-item__sources a:hover { text-decoration: underline; }
.exam-reference-item .hint { margin: 5px 0 0; font-size: 11px; }
.exam-reference-add { margin-top: 10px; padding: 6px 11px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); font-size: 12px; }
.exam-reference-add:hover:not(:disabled) { border-color: #b8c9d9; color: #355b7d; background: #f6f9fc; }
.exam-reference-add:disabled { cursor: default; opacity: .65; }
.knowledge-breadcrumb { margin: 0 0 8px; color: var(--text-tertiary); font-size: 12px; overflow-wrap: anywhere; }
.detail { margin-left: 0; margin-right: 0; }
@media (max-width: 600px) {
  .tree-toolbar { flex-wrap: wrap; }
  .tree-toolbar input { flex: 1 1 200px; width: auto; }
  .tree-viewport { min-height: 340px; }
  .tree-heading > div { display: grid; gap: 3px; }
}
.question-options { list-style: none; padding: 0; margin: 12px 0; }
.question-options li { display: flex; gap: 10px; align-items: baseline; margin: 6px 0; }
.question-options li > span { color: var(--text-secondary); }
.knowledge-assistant-entry{display:flex;align-items:center;gap:12px;padding:12px 0 16px;margin:4px 0 14px;border-bottom:1px solid var(--border);min-width:0}
.knowledge-assistant-entry :deep(.study-mascot){width:46px;height:50px;flex:0 0 46px}
.knowledge-assistant-entry>div{display:grid;gap:4px;flex:1;min-width:0}.knowledge-assistant-entry strong{font-size:13px;font-weight:500}.knowledge-assistant-entry span{font-size:11px;color:var(--text-secondary);line-height:1.6}
.knowledge-assistant-entry>a{font-size:12px;white-space:nowrap;min-height:38px;display:flex;align-items:center;padding:5px 9px;border:1px solid var(--border);border-radius:9px;text-decoration:none}
@media(max-width:600px){.knowledge-assistant-entry{flex-wrap:wrap;gap:8px}.knowledge-assistant-entry>a{margin-left:54px}}
</style>
