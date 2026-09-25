<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { fetchKnowledgeNode, fetchKnowledgeTree, submitNodeSelfAssessment } from "../api/study";
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

type Tab = "overview" | "questions" | "attempts" | "materials";

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

const state = computed(() => treeTask.state.value);
const errorCode = computed(() => treeTask.errorCode.value);
const errorMessage = computed(() => treeTask.errorMessage.value);
const roots = ref<KnowledgeNodeView[]>([]);

const expanded = ref<Set<string>>(new Set());
const selectedId = ref<string | null>(null);
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
function summarize(node: KnowledgeNodeView): { total: number; done: number } {
  const leaves = flattenLeaves(node.children);
  return { total: leaves.length, done: leaves.filter((leaf) => leaf.state === "mastered").length };
}

type GraphNode = { node: KnowledgeNodeView; depth: number; x: number; y: number; parentId: string | null };
const treeGraph = computed(() => {
  const nodes: GraphNode[] = [];
  let leafIndex = 0;
  let maxDepth = 0;
  const visit = (node: KnowledgeNodeView, depth: number, parentId: string | null): number => {
    maxDepth = Math.max(maxDepth, depth);
    const children = expanded.value.has(node.id) ? node.children : [];
    const childYs = children.map((child) => visit(child, depth + 1, node.id));
    const y = childYs.length ? (childYs[0] + childYs[childYs.length - 1]) / 2 : 70 + leafIndex++ * 86;
    nodes.push({ node, depth, x: 34 + depth * 244, y, parentId });
    return y;
  };
  roots.value.forEach((root) => visit(root, 0, null));
  const byId = new Map(nodes.map((entry) => [entry.node.id, entry]));
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

async function load(): Promise<void> {
  const data = await runTree(async () => {
    const response = await fetchKnowledgeTree();
    return response;
  });
  if (!data) return;
  roots.value = data.nodes;
  // 首屏展示完整分叉结构，画布可滚动；父节点仍可逐层收起。
  const next = new Set<string>();
  const expandBranches = (nodes: KnowledgeNodeView[]): void => {
    for (const node of nodes) {
      if (hasChildren(node)) next.add(node.id);
      expandBranches(node.children);
    }
  };
  expandBranches(data.nodes);
  expanded.value = next;
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
  const next = new Set(expanded.value);
  if (next.has(node.id)) next.delete(node.id);
  else next.add(node.id);
  expanded.value = next;
}

async function selectNode(node: KnowledgeNodeView): Promise<void> {
  if (!node.is_assessable) {
    // 父节点只能汇总，不能打开考核视图。
    toggleExpand(node);
    return;
  }
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

onMounted(() => void load());
</script>

<template>
  <section class="page page--knowledge">
    <p class="page-intro">按章节展开知识点，选择叶子查看学习方向。</p>

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
        <div class="tree-heading"><strong>知识结构</strong><span>{{ allLeaves.length }} 个知识点 · 点击节点查看</span></div>
        <div class="tree-viewport">
          <div class="tree-graph" role="tree" :style="{ width: `${treeGraph.width}px`, height: `${treeGraph.height}px` }">
            <svg class="tree-edges" :viewBox="`0 0 ${treeGraph.width} ${treeGraph.height}`" aria-hidden="true">
              <path v-for="(path, index) in treeGraph.paths" :key="index" :d="path" />
            </svg>
            <div v-for="row in treeGraph.nodes" :key="row.node.id" class="tree-entry" :class="{ 'tree-entry--root': row.depth === 0 }" :style="{ left: `${row.x}px`, top: `${row.y}px` }" role="treeitem" :aria-level="row.depth + 1" :aria-expanded="hasChildren(row.node) ? expanded.has(row.node.id) : undefined">
              <div class="tree-row">
                <button v-if="hasChildren(row.node)" type="button" class="tree-toggle" :aria-label="expanded.has(row.node.id) ? `收起${row.node.name}` : `展开${row.node.name}`" @click="toggleExpand(row.node)">{{ expanded.has(row.node.id) ? "▾" : "▸" }}</button>
                <span v-else class="tree-toggle tree-toggle--empty" aria-hidden="true"></span>
                <button type="button" class="tree-node" :class="{ 'tree-node--selected': selectedId === row.node.id, 'tree-node--branch': hasChildren(row.node) }" :data-testid="`tree-node-${row.node.code}`" @click="selectNode(row.node)">{{ row.node.name }}</button>
              </div>
              <span v-if="hasChildren(row.node)" class="tree-progress">{{ summarize(row.node).done }}/{{ summarize(row.node).total }} 已毕业</span>
              <span v-else class="tree-leaf-state" :class="stateTone(row.node.state)"><span class="tree-leaf-dot" aria-hidden="true"></span>{{ stateLabel(row.node.state) }}</span>
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
          <h2 data-testid="detail-title">{{ detail.node.name }}</h2>
          <p class="state" data-testid="detail-state">
            {{ stateLabel(detail.node.state) }}
          </p>

          <nav class="mode-switch">
            <button type="button" :class="{ active: tab === 'overview' }" data-testid="tab-overview" @click="tab = 'overview'">概览</button>
            <button type="button" :class="{ active: tab === 'questions' }" data-testid="tab-questions" @click="tab = 'questions'">题库</button>
            <button type="button" :class="{ active: tab === 'attempts' }" data-testid="tab-attempts" @click="tab = 'attempts'">练习记录</button>
            <button type="button" :class="{ active: tab === 'materials' }" data-testid="tab-materials" @click="tab = 'materials'">关联资料</button>
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
            <p v-if="detail.node.summary"><strong>知识摘要：</strong>{{ detail.node.summary }}</p>
            <p v-if="detail.node.learning_goal"><strong>学习目标：</strong>{{ detail.node.learning_goal }}</p>

            <p v-if="detail.node.next_step" class="notice" data-testid="next-step">
              <strong>下一步：</strong>{{ detail.node.next_step }}
            </p>
            <details class="knowledge-advanced" data-testid="knowledge-advanced">
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
              <dt>已有真实变式题确认</dt>
              <dd data-testid="has-variant">{{ detail.node.has_real_variant ? "是" : "否" }}</dd>
              <dt>下次复习</dt>
              <dd>{{ formatTime(detail.node.next_review_at) }}</dd>
            </dl>
            </details>

            <!-- 叶子整体自评：只有 is_assessable 叶子才有这一组按钮 -->
            <div class="actions actions--grades" data-testid="node-assessment">
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
            <p class="hint">整体自评会记录基础确认，不会算作做过题。</p>
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

          <!-- 关联资料 -->
          <section v-else class="card" data-testid="panel-materials">
            <p v-if="!detail.materials_ready" class="state state--empty">
              资料索引接入后可显示该知识点的关联资料片段。
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
.tree-viewport { border: 1px solid var(--border); border-radius: 14px; }</style>
