<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import AppIcon from "../components/AppIcon.vue";
import {
  appendExamReferencesToday,
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
  ExamQuestionReferenceView,
  MasteryState,
  NodeSelfAssessmentResponse,
} from "../types/practice";
import { useAsyncTask } from "../composables/useAsyncTask";

type Tab = "overview" | "questions" | "attempts" | "materials" | "exam";

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
const roots = ref<KnowledgeNodeView[]>([]);

const expanded = ref<Set<string>>(new Set());
const selectedId = ref<string | null>(null);
const treeSearch = ref("");
const rootScope = ref("");
const searchCollapsed = ref(new Set<string>());
const branchLimits = ref<Record<string, number>>({});
const BRANCH_BATCH = 20;
let treeInitialized = false;
watch(treeSearch, () => { searchCollapsed.value = new Set(); branchLimits.value = {}; });

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
  return treeSearch.value.trim() ? !searchCollapsed.value.has(node.id) : expanded.value.has(node.id);
}
function findPath(nodes: KnowledgeNodeView[], id: string): KnowledgeNodeView[] {
  for (const node of nodes) {
    if (node.id === id) return [node];
    const rest = findPath(node.children, id);
    if (rest.length) return [node, ...rest];
  }
  return [];
}
const selectedPath = computed(() => selectedId.value ? findPath(roots.value, selectedId.value) : []);
function collapseTree(): void {
  if (treeSearch.value.trim()) searchCollapsed.value = new Set(treeGraph.value.nodes.filter((row) => !row.moreFor).map((row) => row.node.id));
  else expanded.value = new Set(visibleRoots.value.map((node) => node.id));
  branchLimits.value = {};
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
const detailPanel = ref<HTMLElement | null>(null);

const nodeSubmitting = ref(false);
const nodeNotice = ref<string | null>(null);
const nodeError = ref<string | null>(null);
const queuedExamReferenceIds = ref<Set<string>>(new Set());
const addingExamReferenceId = ref<string | null>(null);
const examReferenceNotice = ref<string | null>(null);
const examReferenceError = ref<string | null>(null);

async function refreshQueuedExamReferences(): Promise<void> {
  try {
    const today = await fetchToday();
    queuedExamReferenceIds.value = new Set(
      isTodayActive(today)
        ? today.items.flatMap((item) => item.exam_reference?.id ? [item.exam_reference.id] : [])
        : [],
    );
  } catch {
    // 详情仍可正常浏览；用户点击加入时会看到具体操作错误。
    queuedExamReferenceIds.value = new Set();
  }
}

async function addExamReference(reference: ExamQuestionReferenceView): Promise<void> {
  if (queuedExamReferenceIds.value.has(reference.id)) return;
  addingExamReferenceId.value = reference.id;
  examReferenceNotice.value = null;
  examReferenceError.value = null;
  try {
    const today = await appendExamReferencesToday([reference.id]);
    if (!isTodayActive(today)) throw new Error("今日练习卷没有成功创建");
    queuedExamReferenceIds.value = new Set(
      today.items.flatMap((item) => item.exam_reference?.id ? [item.exam_reference.id] : []),
    );
    examReferenceNotice.value = "已加入今日学习。完成原卷后按实际表现自评；标记“已掌握”会计入本知识点毕业证据。";
  } catch (error) {
    examReferenceError.value = error instanceof ApiError ? error.message : "加入今日学习失败，请重试。";
  } finally {
    addingExamReferenceId.value = null;
  }
}

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
const referenceOnlyCount = computed(() =>
  roots.value.reduce((total, root) => total + summarize(root).references, 0),
);

type GraphNode = { key: string; node: KnowledgeNodeView; depth: number; x: number; y: number; parentId: string | null; moreFor?: string; remaining?: number };
const treeGraph = computed(() => {
  const nodes: GraphNode[] = [];
  let leafIndex = 0;
  let maxDepth = 0;
  const visit = (node: KnowledgeNodeView, depth: number, parentId: string | null): number => {
    maxDepth = Math.max(maxDepth, depth);
    const limit = branchLimits.value[node.id] ?? BRANCH_BATCH;
    const children = branchIsOpen(node) ? node.children.slice(0, limit) : [];
    const childYs = children.map((child) => visit(child, depth + 1, node.id));
    if (branchIsOpen(node) && node.children.length > limit) {
      const moreY = 70 + leafIndex++ * 86;
      nodes.push({ key: `more-${node.id}`, node, depth: depth + 1, x: 34 + (depth + 1) * 244, y: moreY, parentId: node.id, moreFor: node.id, remaining: node.children.length - limit });
      childYs.push(moreY);
    }
    const y = childYs.length ? (childYs[0] + childYs[childYs.length - 1]) / 2 : 70 + leafIndex++ * 86;
    nodes.push({ key: node.id, node, depth, x: 34 + depth * 244, y, parentId });
    return y;
  };
  visibleRoots.value.forEach((root) => visit(root, 0, null));
  const byId = new Map(nodes.filter((entry) => !entry.moreFor).map((entry) => [entry.node.id, entry]));
  const paths = nodes.flatMap((entry) => {
    const parent = entry.parentId ? byId.get(entry.parentId) : null;
    if (!parent) return [];
    const startX = parent.x + 190;
    const endX = entry.x;
    const midX = (startX + endX) / 2;
    return [`M ${startX} ${parent.y} C ${midX} ${parent.y}, ${midX} ${entry.y}, ${endX} ${entry.y}`];
  });
  return {
    nodes,
    paths,
    width: Math.max(760, 34 + maxDepth * 244 + 224),
    height: Math.max(420, 140 + Math.max(0, leafIndex - 1) * 86),
  };
});
function hasChildren(node: KnowledgeNodeView): boolean {
  return node.children.length > 0;
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

const examReferenceGroups = computed(() => {
  const groups = new Map<number, ExamQuestionReferenceView[]>();
  for (const reference of detail.value?.exam_references ?? []) {
    const group = groups.get(reference.year) ?? [];
    group.push(reference);
    groups.set(reference.year, group);
  }
  return [...groups.entries()]
    .sort(([yearA], [yearB]) => yearB - yearA)
    .map(([year, references]) => ({ year, references }));
});

async function load(): Promise<void> {
  const data = await runTree(async () => {
    const response = await fetchKnowledgeTree();
    return response;
  });
  if (!data) return;
  roots.value = data.nodes;
  if (!treeInitialized) expanded.value = new Set(data.nodes.map((node) => node.id));
  treeInitialized = true;
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
  if (treeSearch.value.trim()) {
    const next = new Set(searchCollapsed.value);
    if (next.has(node.id)) next.delete(node.id); else next.add(node.id);
    searchCollapsed.value = next;
    return;
  }
  const next = new Set(expanded.value);
  if (next.has(node.id)) next.delete(node.id);
  else next.add(node.id);
  expanded.value = next;
}

async function selectNode(node: KnowledgeNodeView, syncUrl = true): Promise<void> {
  // 展开/收起由箭头控制；点击名称始终打开节点，父节点也有章节导读。
  if (syncUrl) void router.replace({ path: "/knowledge", query: { node: node.code } });
  const kpId = node.id;
  selectedId.value = kpId;
  await nextTick();
  detailPanel.value?.scrollIntoView({ behavior: "smooth", block: "start" });
  tab.value = "overview";
  nodeNotice.value = null;
  nodeError.value = null;
  resetDetail();
  const data = await runDetail(async () => normalizeDetail(await fetchKnowledgeNode(kpId)));
  // 过期/被取消的选择：结果已经不重要，直接丢弃。
  if (selectedId.value !== kpId) return;
  if (data) return;
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
    await load();
    const leaf = findLeaf(kpId);
    if (leaf) await selectNode(leaf);

    // 基础确认数由后端给出：绝不在前端假装用户做了两题。
    const credit =
      result.manual_credit_count > 0 ? `基础确认 +${result.manual_credit_count}` : "基础确认为 0";
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

onMounted(async () => {
  await Promise.all([load(), refreshQueuedExamReferences()]);
  const code = typeof route.query.node === "string" ? route.query.node : null;
  if (!code) return;
  const node = findNodeByCode(roots.value, code);
  if (!node) return;
  treeSearch.value = node.code;
  await selectNode(node, false);
  if (node.is_assessable && !node.is_reference_only && route.query.tab === "questions") tab.value = "questions";
});
</script>

<template>
  <section class="page page--knowledge">
    <p class="page-intro">按章节阅读知识讲解，再到题库检验理解。</p>

    <p v-if="state === 'loading'" class="state state--loading" data-testid="knowledge-loading">
      正在加载知识树…
    </p>
    <div v-else-if="state === 'error'" class="state state--error" data-testid="knowledge-error">
      <p>{{ errorMessage }}</p>
      <p v-if="errorCode" class="state__code">错误码：{{ errorCode }}</p>
      <button type="button" @click="load">重试</button>
    </div>

    <div v-else class="knowledge-layout">
      <section class="tree" data-testid="knowledge-tree" aria-label="知识树">
        <div class="tree-heading"><div><strong>知识结构</strong><span>{{ allLeaves.length }} 个学习知识点 · {{ referenceOnlyCount }} 个历年考点</span></div><button type="button" class="tree-collapse" @click="collapseTree">收起分支</button></div>
        <div class="tree-toolbar">
          <input v-model="treeSearch" type="search" aria-label="搜索知识点名称或编号" placeholder="搜索知识点或章节" data-testid="knowledge-search" />
          <select v-if="roots.length > 1" v-model="rootScope" aria-label="知识树学科范围"><option value="">全部学科</option><option v-for="root in roots" :key="root.id" :value="root.id">{{ root.name }}</option></select>
          <button v-if="treeSearch" type="button" @click="treeSearch = ''">清除搜索</button>
        </div>
        <p v-if="!visibleRoots.length" class="state state--empty" data-testid="knowledge-search-empty">没有找到匹配的知识点，试试其他名称或编号。</p>
        <div v-else class="tree-viewport" tabindex="0" aria-label="知识树画布，可横向和纵向滚动">
          <div class="tree-graph" role="tree" :style="{ width: `${treeGraph.width}px`, height: `${treeGraph.height}px` }">
            <svg class="tree-edges" :viewBox="`0 0 ${treeGraph.width} ${treeGraph.height}`" aria-hidden="true">
              <path v-for="(path, index) in treeGraph.paths" :key="index" :d="path" />
            </svg>
            <div v-for="row in treeGraph.nodes" :key="row.key" class="tree-entry" :class="{ 'tree-entry--root': row.depth === 0, 'tree-entry--more': row.moreFor }" :style="{ left: `${row.x}px`, top: `${row.y}px` }" role="treeitem" :aria-level="row.depth + 1" :aria-expanded="!row.moreFor && hasChildren(row.node) ? branchIsOpen(row.node) : undefined">
              <button v-if="row.moreFor" type="button" class="tree-more" :aria-label="`显示更多${row.node.name}下的节点`" @click="showMore(row.moreFor)">显示更多 <small>还剩 {{ row.remaining }} 项</small></button>
              <div v-else class="tree-row">
                <button v-if="hasChildren(row.node)" type="button" class="tree-toggle" :aria-label="branchIsOpen(row.node) ? `收起${row.node.name}` : `展开${row.node.name}`" @click="toggleExpand(row.node)">{{ branchIsOpen(row.node) ? "▾" : "▸" }}</button>
                <span v-else class="tree-toggle tree-toggle--empty" aria-hidden="true"></span>
                <button type="button" class="tree-node" :class="{ 'tree-node--selected': selectedId === row.node.id, 'tree-node--branch': hasChildren(row.node) }" :data-testid="`tree-node-${row.node.code}`" @click="selectNode(row.node)">{{ row.node.name }}</button>
              </div>
              <span v-if="!row.moreFor && hasChildren(row.node)" class="tree-progress">
                <template v-if="summarize(row.node).total">{{ summarize(row.node).done }}/{{ summarize(row.node).total }} 已毕业</template>
                <template v-else>{{ summarize(row.node).references }} 个历年考点</template>
                <template v-if="summarize(row.node).total && summarize(row.node).references"> · {{ summarize(row.node).references }} 个历年考点</template>
              </span>
              <span v-else-if="!row.moreFor && row.node.is_reference_only" class="tree-leaf-state tree-leaf-state--reference" :class="stateTone(row.node.state)"><span class="tree-leaf-dot" aria-hidden="true"></span>{{ stateLabel(row.node.state) }} · 历年真题</span>
              <span v-else-if="!row.moreFor" class="tree-leaf-state" :class="stateTone(row.node.state)"><span class="tree-leaf-dot" aria-hidden="true"></span>{{ stateLabel(row.node.state) }}</span>
            </div>
          </div>
        </div>
      </section>

      <div ref="detailPanel" class="detail">
        <p v-if="!selectedId" class="state state--empty" data-testid="knowledge-empty">
          选择树上的知识点查看详情；章节可继续展开。
        </p>

        <p v-else-if="detailLoading" class="state state--loading" data-testid="detail-loading">
          正在加载知识点详情…
        </p>
        <p v-else-if="detailError" class="state state--error">{{ detailError }}</p>

        <div v-else-if="detail" data-testid="knowledge-detail">
          <p class="knowledge-breadcrumb" data-testid="knowledge-breadcrumb">{{ selectedPath.map((node) => node.name).join(' / ') }}</p>
          <h2 data-testid="detail-title">{{ detail.node.name }}</h2>
          <p v-if="detail.node.is_reference_only" class="hint exam-reference-note" data-testid="exam-reference-only-note">
            {{ detail.node.code.includes('.family.') ? '这是项目按原始标签整理的跨年份专题汇总，不是官方考点分类；列表会保留每道题的原始标签。原卷题干不在系统内，可打开来源或本地原卷完成后加入今日学习。' : '这是历年真题知识节点：这里提供原卷来源，不包含题干。完成原卷后在今日学习自评；标记“已掌握”将作为本节点的毕业证据。' }}
          </p>
          <p class="state" data-testid="detail-state">
            {{ stateLabel(detail.node.state) }}
          </p>

          <nav class="mode-switch">
            <button type="button" :class="{ active: tab === 'overview' }" data-testid="tab-overview" @click="tab = 'overview'">概览</button>
            <button v-if="detail.node.is_assessable && !detail.node.is_reference_only" type="button" :class="{ active: tab === 'questions' }" data-testid="tab-questions" @click="tab = 'questions'">题库</button>
            <button v-if="detail.node.is_assessable" type="button" :class="{ active: tab === 'attempts' }" data-testid="tab-attempts" @click="tab = 'attempts'">练习记录</button>
            <button v-if="detail.exam_references.length || detail.node.is_reference_only" type="button" :class="{ active: tab === 'exam' }" data-testid="tab-exam-references" @click="tab = 'exam'">历年真题 <span class="exam-reference-count">{{ detail.exam_references.length }}</span></button>
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
                <small>{{ detail.node.is_assessable ? "概念、例题与易错点" : "本章学习顺序与知识点入口" }}</small>
              </span>
              <span aria-hidden="true">→</span>
            </RouterLink>
            <p v-if="detail.node.summary"><strong>知识摘要：</strong>{{ detail.node.summary }}</p>
            <p v-if="detail.node.learning_goal"><strong>学习目标：</strong>{{ detail.node.learning_goal }}</p>

            <p v-if="detail.node.next_step" class="notice" data-testid="next-step">
              <strong>下一步：</strong>{{ detail.node.next_step }}
            </p>
            <details v-if="detail.node.is_assessable" class="knowledge-advanced" data-testid="knowledge-advanced">
              <summary>查看毕业进度与考核要求</summary>
            <!-- 毕业进度：逐项来自后端 gap_items，前端不自己算毕业条件 -->
            <h3 class="section-title">毕业进度</h3>
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
              <dt>基础确认（节点整体自评）</dt>
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
            </details>

            <!-- 叶子整体自评：只有 is_assessable 叶子才有这一组按钮 -->
            <div v-if="detail.node.is_assessable" class="actions actions--grades" data-testid="node-assessment">
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-mastered" @click="nodeAssess('mastered')">
                我已掌握
              </button>
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-partial" @click="nodeAssess('partial')">
                我部分掌握
              </button>
              <button type="button" :disabled="nodeSubmitting" data-testid="node-self-not-mastered" @click="nodeAssess('not_mastered')">
                我未掌握
              </button>
            </div>
            <p v-if="detail.node.is_assessable" class="hint">整体自评会记录基础确认，不会算作做过题。</p>
            <p v-if="nodeNotice" class="notice" data-testid="node-notice">{{ nodeNotice }}</p>
            <p v-if="nodeError" class="form-error">{{ nodeError }}</p>
          </section>

          <!-- 题库：只显示题干，不显示答案 -->
          <section v-else-if="tab === 'questions'" class="card" data-testid="question-bank">
            <p v-if="detail.questions.length === 0" class="state state--empty">该知识点还没有题目。</p>
            <ul v-else>
              <li v-for="question in detail.questions" :key="question.id" class="pool-item">
                <p>{{ question.stem }}</p>
                <span class="tag tag--muted">{{ question.question_type }}</span>
                <span class="tag tag--muted">{{ question.difficulty }}</span>
                <span v-if="question.is_variant" class="tag">变式题</span>
              </li>
            </ul>
            <p class="hint">题库不显示答案；答案详解只在答题页查看答案时读取。</p>
          </section>

          <!-- 练习记录 -->
          <section v-else-if="tab === 'attempts'" class="card" data-testid="attempt-history">
            <p v-if="detail.attempts.length === 0" class="state state--empty">还没有练习记录。</p>
            <ul v-else>
              <li v-for="attempt in detail.attempts" :key="attempt.id" class="attempt-item">
                <p>{{ attempt.question_stem }}</p>
                <span class="tag" :class="stateTone(attempt.result_state)">{{ gradeLabel(attempt.self_grade) }}</span>
                <span class="tag tag--muted">{{ formatTime(attempt.submitted_at) }}</span>
                <span class="tag tag--muted">{{ reasonCodeLabel(attempt.reason_code) }}</span>
                <p v-if="attempt.raw_answer" class="hint">我的作答：{{ attempt.raw_answer }}</p>
              </li>
            </ul>
          </section>

          <section v-else-if="tab === 'exam'" class="card exam-reference-panel" data-testid="exam-reference-panel">
            <p class="hint">索引仅记录来源提供的考点标签；标签不是官方命题标注，可能存在分类争议。需要练习请打开原卷核对题号。</p>
            <p v-if="examReferenceGroups.length === 0" class="state state--empty">这个知识点暂时没有已导入的历年题号。</p>
            <details v-for="(group, index) in examReferenceGroups" :key="group.year" class="exam-year" :open="index === 0">
              <summary>{{ group.year }} 年 · {{ group.references.length }} 条题号关联</summary>
              <ul class="exam-reference-list">
                <li v-for="reference in group.references" :key="reference.id" class="exam-reference-item">
                  <div class="exam-reference-item__heading">
                    <strong>第 {{ reference.question_number }} 题</strong>
                    <span>{{ reference.subject }}</span>
                    <span v-if="reference.topic_label">{{ reference.topic_label }}</span>
                  </div>
                  <p v-if="reference.source_topic_label !== reference.topic_label" class="hint">原索引标签：{{ reference.source_topic_label }}</p>
                  <div class="exam-reference-item__sources">
                    <a v-if="reference.question_source_url" :href="reference.question_source_url" target="_blank" rel="noopener noreferrer">打开题目来源 ↗</a>
                    <a v-if="reference.topic_source_url" :href="reference.topic_source_url" target="_blank" rel="noopener noreferrer">查看标签来源 ↗</a>
                    <span>本地原卷目录：桌面 / 考研知识点 / {{ reference.local_folder }}</span>
                  </div>
                  <p class="hint">{{ reference.source_note }}</p>
                  <button
                    type="button"
                    class="exam-reference-add"
                    :disabled="addingExamReferenceId === reference.id || queuedExamReferenceIds.has(reference.id)"
                    :data-testid="`add-exam-reference-${reference.id}`"
                    @click="addExamReference(reference)"
                  >
                    {{ queuedExamReferenceIds.has(reference.id) ? "已在今日学习" : addingExamReferenceId === reference.id ? "正在加入…" : "加入今日学习" }}
                  </button>
                </li>
              </ul>
            </details>
            <p v-if="examReferenceNotice" class="notice" data-testid="exam-reference-notice">{{ examReferenceNotice }}</p>
            <p v-if="examReferenceError" class="form-error" data-testid="exam-reference-error">{{ examReferenceError }}</p>
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
</style>
