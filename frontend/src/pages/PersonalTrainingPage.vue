<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ApiError } from "../api/client";
import { useRoute } from "vue-router";
import { createChatSession } from "../api/chat";
import { fetchKnowledgeTree } from "../api/study";
import {
  answerPersonalTrainingItem,
  appendPersonalTraining,
  createNextPersonalTraining,
  createPersonalTraining,
  listPersonalTrainings,
  readPersonalTraining,
  readPersonalTrainingReport,
  savePersonalTrainingDraft,
  transitionPersonalTraining,
  type PersonalTrainingReport,
  type PersonalTrainingView,
} from "../api/personalTrainings";
import type { KnowledgeNodeView } from "../types/practice";

const OWNER_KEY = "kaoyan.personal-training.owner-session.v1";
const SELECTED_TRAINING_KEY = "kaoyan.personal-training.selected.v1";
const ownerSessionId = ref("");
const route = useRoute();
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const tree = ref<KnowledgeNodeView[]>([]);
const trainings = ref<PersonalTrainingView[]>([]);
const selectedTrainingId = ref("");
const training = ref<PersonalTrainingView | null>(null);
const report = ref<PersonalTrainingReport | null>(null);
const selectedIds = ref<string[]>([]);
const title = ref("个人专项训练");
const questionCount = ref("");
const targetMinutes = ref(30);
const difficulty = ref<"any" | "basic" | "improved" | "comprehensive">("any");
const questionType = ref("");
const basis = ref<"selected" | "recent_mistakes">("selected");
const appendCount = ref(2);
const answers = reactive<Record<string, string>>({});
const idempotencyKeys = new Map<string, string>();
const draftTimers = new Map<string, number>();
const draftRevisions = new Map<string, number>();
const draftSaves = new Map<string, Promise<void>>();

watch(selectedTrainingId, (id) => {
  try {
    if (id) localStorage.setItem(SELECTED_TRAINING_KEY, id);
    else localStorage.removeItem(SELECTED_TRAINING_KEY);
  } catch { /* server remains the source of truth for saved training */ }
});

function keyFor(name: string, signature: string): string {
  const slot = `${name}:${signature}`;
  let value = idempotencyKeys.get(slot);
  if (!value) {
    value = `${name}-${crypto.randomUUID()}`;
    idempotencyKeys.set(slot, value);
  }
  return value;
}
function clearKey(name: string, signature: string): void { idempotencyKeys.delete(`${name}:${signature}`); }

function errorText(cause: unknown): string {
  if (!(cause instanceof ApiError)) return "操作失败，请保留当前训练并重试。";
  const messages: Record<string, string> = {
    personal_training_recent_mistakes_unavailable: "没有可用于安排训练的真实错题记录。",
    personal_training_questions_unavailable: "当前范围没有符合条件的题目，训练未创建或未追加。",
    personal_training_node_not_assessable: "所选知识点暂不能安排练习。",
    personal_training_question_no_longer_eligible: "题目资格已变化，本次答案未保存。请刷新训练。",
    personal_training_version_conflict: "训练状态已在其他页面更新，请重新读取后继续。",
    personal_training_state_conflict: "当前训练状态不允许此操作，请先恢复训练。",
    personal_training_session_forbidden: "训练空间不可用，请刷新页面重试。",
    personal_training_draft_revision_conflict: "未提交答案已在其他页面更新，请刷新后继续编辑。",
  };
  return messages[cause.code ?? ""] ?? (cause.message || "操作失败，请稍后重试。");
}

function flatten(nodes: KnowledgeNodeView[], parent = ""): Array<{ id: string; name: string; label: string; count: number }> {
  return nodes.flatMap((node) => {
    const path = parent ? `${parent} / ${node.name}` : node.name;
    const own = node.is_assessable && !node.is_reference_only
      ? [{ id: node.id, name: node.name, label: path, count: node.practice_eligible_question_count ?? 0 }]
      : [];
    return [...own, ...flatten(node.children ?? [], path)];
  });
}
const knowledgePoints = computed(() => flatten(tree.value));
const canCreate = computed(() => !busy.value && (basis.value === "recent_mistakes" || selectedIds.value.length > 0));

function toggleKnowledgePoint(id: string, checked: boolean): void {
  selectedIds.value = checked
    ? [...new Set([...selectedIds.value, id])]
    : selectedIds.value.filter((value) => value !== id);
}

async function ensureOwner(): Promise<string> {
  const queryOwner = typeof route.query.owner_session_id === "string" ? route.query.owner_session_id : "";
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(queryOwner)) {
    ownerSessionId.value = queryOwner;
    return queryOwner;
  }
  let saved = "";
  try { saved = localStorage.getItem(OWNER_KEY) ?? ""; } catch { /* session can still be created for this view */ }
  if (saved) {
    ownerSessionId.value = saved;
    return saved;
  }
  const created = await createChatSession("个人专项训练空间", "builtin", { purpose: "study" });
  ownerSessionId.value = created.session_id;
  try { localStorage.setItem(OWNER_KEY, created.session_id); } catch { /* list can be reloaded after the current view */ }
  return created.session_id;
}

async function refreshTrainings(preferId = selectedTrainingId.value): Promise<void> {
  const rows = await listPersonalTrainings(ownerSessionId.value);
  trainings.value = rows;
  const nextId = rows.some((row) => row.training_id === preferId) ? preferId : rows[0]?.training_id ?? "";
  selectedTrainingId.value = nextId;
  training.value = nextId ? rows.find((item) => item.training_id === nextId) ?? null : null;
  if (training.value) restoreDrafts(training.value);
}

function restoreDrafts(value: PersonalTrainingView): void {
  for (const item of value.items) {
    draftRevisions.set(item.item_id, item.draft_revision ?? 0);
    if (item.completed) continue;
    const saved = item.options ? item.draft_selected_option : item.draft_answer;
    if (saved !== null && saved !== undefined) answers[item.item_id] = saved;
    else if (!(item.item_id in answers)) answers[item.item_id] = "";
  }
}

function queueDraftSave(itemId: string): void {
  const old = draftTimers.get(itemId);
  if (old !== undefined) window.clearTimeout(old);
  const timer = window.setTimeout(() => {
    draftTimers.delete(itemId);
    void persistDraft(itemId);
  }, 450);
  draftTimers.set(itemId, timer);
}

function persistDraft(itemId: string): Promise<void> {
  const prior = draftSaves.get(itemId) ?? Promise.resolve();
  const task = prior.catch(() => undefined).then(async () => {
    const current = training.value;
    if (!current || current.status !== "active") return;
    const item = current.items.find((row) => row.item_id === itemId);
    if (!item || item.completed) return;
    const value = answers[itemId] ?? "";
    const response = await savePersonalTrainingDraft(current.training_id, itemId, {
      owner_session_id: ownerSessionId.value,
      expected_draft_revision: draftRevisions.get(itemId) ?? item.draft_revision ?? 0,
      draft_answer: item.options ? null : value,
      draft_selected_option: item.options ? value : null,
    });
    const updatedItem = response.items.find((row) => row.item_id === itemId);
    if (updatedItem) draftRevisions.set(itemId, updatedItem.draft_revision);
    // A response for an older keystroke must never replace newer local input.
    if ((answers[itemId] ?? "") === value && training.value?.training_id === response.training_id) {
      training.value = response;
      trainings.value = trainings.value.map((row) => row.training_id === response.training_id ? response : row);
    }
  }).catch((cause: unknown) => {
    error.value = errorText(cause);
  });
  draftSaves.set(itemId, task);
  return task;
}

function flushDraft(itemId: string): Promise<void> {
  const timer = draftTimers.get(itemId);
  if (timer !== undefined) { window.clearTimeout(timer); draftTimers.delete(itemId); }
  return persistDraft(itemId);
}

async function flushPendingDrafts(): Promise<void> {
  const ids = [...draftTimers.keys()];
  await Promise.all(ids.map((itemId) => flushDraft(itemId)));
  await Promise.all([...draftSaves.values()]);
}

async function reloadSelected(): Promise<void> {
  await flushPendingDrafts();
  if (!selectedTrainingId.value) { training.value = null; report.value = null; return; }
  busy.value = true; error.value = "";
  try {
    const fresh = await readPersonalTraining(selectedTrainingId.value, ownerSessionId.value);
    training.value = fresh;
    restoreDrafts(fresh);
    report.value = fresh.status === "completed"
      ? await readPersonalTrainingReport(selectedTrainingId.value, ownerSessionId.value)
      : null;
    trainings.value = trainings.value.map((row) => row.training_id === fresh.training_id ? fresh : row);
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

async function initialize(): Promise<void> {
  if (!loading.value) await flushPendingDrafts();
  loading.value = true; error.value = "";
  try {
    await ensureOwner();
    try { selectedTrainingId.value = localStorage.getItem(SELECTED_TRAINING_KEY) ?? ""; }
    catch { selectedTrainingId.value = ""; }
    if (typeof route.query.training_id === "string"
        && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(route.query.training_id)) {
      selectedTrainingId.value = route.query.training_id;
    }
    const [knowledge] = await Promise.all([fetchKnowledgeTree()]);
    tree.value = knowledge.nodes;
    await refreshTrainings();
  } catch (cause) { error.value = errorText(cause); }
  finally { loading.value = false; }
}

async function createTraining(): Promise<void> {
  const count = questionCount.value.trim() ? Number(questionCount.value) : null;
  const payload = {
    owner_session_id: ownerSessionId.value, title: title.value.trim() || "个人专项训练",
    knowledge_point_ids: basis.value === "recent_mistakes" ? selectedIds.value : selectedIds.value,
    question_count: count, target_minutes: targetMinutes.value,
    difficulty: difficulty.value, question_type: questionType.value || null, basis: basis.value,
  } as const;
  const signature = JSON.stringify(payload);
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const created = await createPersonalTraining({ ...payload, request_key: keyFor("training-create", signature) });
    clearKey("training-create", signature);
    training.value = created; selectedTrainingId.value = created.training_id; report.value = null;
    await refreshTrainings(created.training_id);
    notice.value = created.inventory_shortfall > 0 || created.minutes_shortfall > 0
      ? `训练已建立，当前题库可分配 ${created.item_count} 道，时长差额约 ${created.minutes_shortfall} 分钟。`
      : "专项训练已建立，进度将独立保存，不影响今日正式卷。";
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

async function runTransition(action: "pause" | "resume" | "finish"): Promise<void> {
  if (!training.value) return;
  const current = training.value;
  const signature = `${current.training_id}:${current.version}`;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await transitionPersonalTraining(current.training_id, action, {
      owner_session_id: ownerSessionId.value, request_key: keyFor(action, signature), expected_version: current.version,
    });
    clearKey(action, signature); training.value = result; report.value = null;
    await refreshTrainings(result.training_id);
    notice.value = action === "pause" ? "训练已暂停，可以之后继续。" : action === "resume" ? "训练已恢复。" : "训练已结束，报告已更新。";
    if (action === "finish") report.value = await readPersonalTrainingReport(result.training_id, ownerSessionId.value);
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

async function appendQuestions(): Promise<void> {
  if (!training.value) return;
  const current = training.value;
  const signature = `${current.training_id}:${current.version}:${appendCount.value}`;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await appendPersonalTraining(current.training_id, {
      owner_session_id: ownerSessionId.value, request_key: keyFor("training-append", signature),
      expected_version: current.version, question_count: appendCount.value,
    });
    clearKey("training-append", signature); training.value = result; report.value = null;
    await refreshTrainings(result.training_id);
    notice.value = `已追加 ${Math.max(0, result.item_count - current.item_count)} 道题。`;
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

async function submitAnswer(itemId: string): Promise<void> {
  if (!training.value) return;
  await flushDraft(itemId);
  await draftSaves.get(itemId);
  const current = training.value;
  const item = current.items.find((row) => row.item_id === itemId);
  if (!item) return;
  const answer = answers[itemId]?.trim() ?? "";
  if (!answer) { error.value = "请先填写答案。"; return; }
  const signature = `${current.training_id}:${itemId}:${current.version}:${answer}`;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const result = await answerPersonalTrainingItem(current.training_id, itemId, {
      owner_session_id: ownerSessionId.value, idempotency_key: keyFor("training-answer", signature),
      expected_version: current.version,
      raw_answer: item.options ? null : answer, selected_option: item.options ? answer : null,
    });
    clearKey("training-answer", signature); training.value = result; report.value = null;
    await refreshTrainings(result.training_id);
    notice.value = "答案已保存到本专项训练中。";
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

async function createNextRound(): Promise<void> {
  if (!training.value) return;
  const current = training.value;
  const signature = `${current.training_id}:${current.version}:next`;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const next = await createNextPersonalTraining(current.training_id, {
      owner_session_id: ownerSessionId.value, request_key: keyFor("training-next", signature),
      question_count: null, target_minutes: current.target_minutes,
    });
    clearKey("training-next", signature); training.value = next; selectedTrainingId.value = next.training_id;
    report.value = null; await refreshTrainings(next.training_id); notice.value = "已根据本专项的实际答题结果建立下一轮训练。";
  } catch (cause) { error.value = errorText(cause); }
  finally { busy.value = false; }
}

onMounted(initialize);
onBeforeUnmount(() => {
  for (const itemId of [...draftTimers.keys()]) void flushDraft(itemId);
});
</script>

<template>
  <section class="training-page" aria-label="个人专项训练">
    <header class="training-heading">
      <div><p class="eyebrow">独立练习空间</p><h2>专项训练</h2><p>使用正式题库中合格题目；专项题目和作答记录独立保存，不会改动今日正式卷。</p></div>
      <button type="button" :disabled="loading || busy" @click="initialize">刷新</button>
    </header>
    <p v-if="error" class="training-message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="training-message success" role="status">{{ notice }}</p>
    <p v-if="loading" class="training-muted">正在读取知识点和已有专项……</p>
    <div v-else class="training-layout">
      <form class="training-create" @submit.prevent="createTraining">
        <h3>安排一组训练</h3>
        <label>训练名称<input v-model="title" maxlength="160" /></label>
        <fieldset class="kp-picker">
          <legend>知识点范围</legend>
          <label v-for="kp in knowledgePoints" :key="kp.id" class="kp-option" :class="{ unavailable: kp.count < 1 }">
            <input type="checkbox" :checked="selectedIds.includes(kp.id)" :disabled="kp.count < 1 || busy" @change="toggleKnowledgePoint(kp.id, ($event.target as HTMLInputElement).checked)" />
            <span>{{ kp.label }}</span><small>{{ kp.count > 0 ? `合格库存 ${kp.count}` : "暂无合格库存" }}</small>
          </label>
        </fieldset>
        <label>选题依据<select v-model="basis"><option value="selected">按已选知识点</option><option value="recent_mistakes">按真实错题记录</option></select></label>
        <div class="field-row">
          <label>题数（留空按时长）<input v-model="questionCount" type="number" min="1" max="30" placeholder="按时长安排" /></label>
          <label>目标分钟<input v-model.number="targetMinutes" type="number" min="5" max="240" /></label>
        </div>
        <div class="field-row">
          <label>难度<select v-model="difficulty"><option value="any">不限</option><option value="basic">基础</option><option value="improved">提高</option><option value="comprehensive">综合</option></select></label>
          <label>题型<select v-model="questionType"><option value="">不限</option><option value="single_choice">单选</option><option value="fill_blank">填空</option><option value="calculation">计算</option><option value="proof">证明</option><option value="discussion">讨论</option></select></label>
        </div>
        <p v-if="basis === 'recent_mistakes'" class="training-muted">只根据已记录的客观错题安排；没有相应记录时会明确提示，不会推测薄弱点。</p>
        <button class="primary" type="submit" :disabled="!canCreate">{{ busy ? "处理中…" : "创建专项训练" }}</button>
      </form>

      <section class="training-active" aria-label="专项详情">
        <div class="training-toolbar"><h3>我的专项</h3><select v-model="selectedTrainingId" aria-label="选择专项训练" @change="reloadSelected"><option value="">选择已保存专项</option><option v-for="row in trainings" :key="row.training_id" :value="row.training_id">{{ row.title }} · {{ row.status === "active" ? "进行中" : row.status === "paused" ? "已暂停" : "已结束" }}</option></select></div>
        <template v-if="training">
          <div class="training-summary"><strong>{{ training.title }}</strong><span>{{ training.status === "active" ? "进行中" : training.status === "paused" ? "已暂停" : "已结束" }} · {{ training.completed_count }}/{{ training.item_count }} 题 · {{ training.actual_minutes }}/{{ training.target_minutes }} 分钟</span><small>方案版本 {{ training.version }} · 独立训练编号 {{ training.training_id.slice(0, 8) }}</small></div>
          <div v-if="training.status === 'active'" class="training-actions">
            <button type="button" :disabled="busy" @click="runTransition('pause')">暂停</button>
            <label>追加<input v-model.number="appendCount" type="number" min="1" max="30" /></label><button type="button" :disabled="busy" @click="appendQuestions">追加题目</button>
            <button type="button" :disabled="busy" @click="runTransition('finish')">结束并分析</button>
          </div>
          <div v-else-if="training.status === 'paused'" class="training-actions"><button type="button" :disabled="busy" @click="runTransition('resume')">继续训练</button><button type="button" :disabled="busy" @click="runTransition('finish')">结束并分析</button></div>
          <ol class="training-questions">
            <li v-for="item in training.items" :key="item.item_id" class="training-question">
              <p><span class="question-no">{{ item.ordinal }}.</span> {{ item.stem }}</p>
              <ul v-if="item.options" class="training-options"><li v-for="(option, key) in item.options" :key="key"><label><input v-model="answers[item.item_id]" type="radio" :name="`answer-${item.item_id}`" :value="key" :disabled="item.completed || training.status !== 'active'" @change="queueDraftSave(item.item_id)" />{{ key }}. {{ option }}</label></li></ul>
              <textarea v-else v-model="answers[item.item_id]" rows="3" placeholder="写下你的答案或主要步骤" :disabled="item.completed || training.status !== 'active'" @input="queueDraftSave(item.item_id)" @blur="flushDraft(item.item_id)"></textarea>
              <div class="question-footer"><small>{{ item.question_type }} · {{ item.difficulty }} · {{ item.estimated_minutes }} 分钟<span v-if="item.completed"> · 已提交（{{ item.latest_result === 'right' ? '正确' : item.latest_result === 'wrong' ? '需复习' : '结果待确认' }}）</span></small><button v-if="!item.completed && training.status === 'active'" type="button" :disabled="busy" @click="submitAnswer(item.item_id)">提交本题</button></div>
            </li>
          </ol>
          <section v-if="training.status === 'completed' && report" class="training-report">
            <h4>训练报告</h4>
            <p>已提交 {{ report?.submitted_count ?? 0 }} 题，正确 {{ report?.right_count ?? 0 }} 题，需复习 {{ report?.wrong_count ?? 0 }} 题。</p>
            <ul v-if="report?.wrong_knowledge_points.length"><li v-for="kp in report.wrong_knowledge_points" :key="kp.kp_id">{{ kp.name }}：{{ kp.wrong_count }} 次错误</li></ul>
            <p v-else class="training-muted">本次没有记录到错误知识点。</p>
            <button v-if="report?.next_round_recommendation" type="button" :disabled="busy" @click="createNextRound">按本次表现安排下一轮</button>
          </section>
          <p v-if="training.inventory_shortfall || training.minutes_shortfall" class="training-muted">库存或时长未达到目标：缺少 {{ training.inventory_shortfall }} 道 / {{ training.minutes_shortfall }} 分钟。训练保留实际可用题目，不会伪造题目。</p>
        </template>
        <p v-else class="training-empty">创建一组专项后，可在这里答题、暂停、刷新后继续，并查看独立训练报告。</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.training-page{max-width:1240px;margin:0 auto;padding:28px clamp(16px,4vw,48px) 56px;color:#344338}.training-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;border-bottom:1px solid #e4e8dd;padding-bottom:22px}.training-heading h2{margin:4px 0 8px;font:34px Georgia,"Songti SC",serif;color:#334538}.training-heading p{margin:0;color:#788275;line-height:1.6}.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase}.training-layout{display:grid;grid-template-columns:minmax(290px,360px) minmax(0,1fr);gap:22px;padding-top:22px}.training-create,.training-active{background:#fffefa;border:1px solid #e4e8dd;border-radius:16px;padding:20px;min-width:0}.training-create h3,.training-active h3{margin:0 0 16px;font-size:19px}.training-create>label,.field-row label{display:grid;gap:6px;margin:12px 0;color:#586657;font-size:13px}.training-create input:not([type=checkbox]):not([type=radio]),.training-create select,.training-toolbar select,.training-actions input{min-height:38px;border:1px solid #dce2d6;border-radius:8px;background:white;padding:7px 9px;color:#344338}.kp-picker{display:grid;gap:4px;max-height:250px;overflow:auto;border:1px solid #e4e8dd;border-radius:10px;padding:10px}.kp-picker legend{padding:0 5px;font-size:13px}.kp-option{display:grid;grid-template-columns:18px minmax(0,1fr) auto;align-items:center;gap:7px;font-size:12px;padding:4px 0}.kp-option small{color:#899283;font-size:10px}.kp-option.unavailable{color:#9a9d92}.field-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.training-create button,.training-active button,.training-heading button{min-height:38px;padding:7px 13px;border:1px solid #d6dfd0;border-radius:9px;background:#fff;color:#415345;cursor:pointer}.training-create button.primary{width:100%;margin-top:10px;background:#4c6d58;border-color:#4c6d58;color:white}.training-create button:disabled,.training-active button:disabled,.training-heading button:disabled{opacity:.52;cursor:not-allowed}.training-muted,.training-empty{color:#818a7d;font-size:13px;line-height:1.6}.training-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px}.training-toolbar h3{margin-bottom:0}.training-toolbar select{max-width:60%}.training-summary{display:grid;gap:5px;margin:18px 0;padding:14px;border-radius:10px;background:#f3f5ed}.training-summary strong{font-size:17px}.training-summary span,.training-summary small{color:#6f7b6d;font-size:12px}.training-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:14px 0}.training-actions label{display:flex;align-items:center;gap:6px;color:#6f7b6d;font-size:12px}.training-actions input{width:68px}.training-questions{display:grid;gap:14px;padding-left:24px}.training-question{padding:14px;border:1px solid #e6e9e1;border-radius:12px}.training-question>p{white-space:pre-wrap;line-height:1.65}.question-no{color:#6a8668;font-weight:700}.training-options{list-style:none;padding:0;display:grid;gap:6px}.training-options label{display:flex;gap:7px;line-height:1.5}.training-question textarea{width:100%;resize:vertical;border:1px solid #dce2d6;border-radius:8px;padding:9px}.question-footer{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:10px}.question-footer small{color:#7d8778;font-size:11px}.training-report{margin-top:20px;padding:16px;border-radius:12px;background:#f5f6ef}.training-report h4{margin:0 0 8px}.training-message{padding:11px 14px;border-radius:10px}.training-message.error{background:#fff2ed;color:#9b4937}.training-message.success{background:#eff5eb;color:#466444}@media(max-width:820px){.training-layout{grid-template-columns:1fr}.training-heading{align-items:flex-start}.training-toolbar{align-items:flex-start;flex-direction:column}.training-toolbar select{max-width:100%;width:100%}}@media(max-width:480px){.training-page{padding:18px 12px 36px}.training-heading{flex-direction:column}.field-row{grid-template-columns:1fr}.question-footer{align-items:flex-start;flex-direction:column}}
</style>
