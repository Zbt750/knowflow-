<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import StudyFocus from "./StudyFocus.vue";
import StudyPaperPreview from "./StudyPaperPreview.vue";
import StudyProgressSummary from "./StudyProgressSummary.vue";
import MarkdownContent from "./MarkdownContent.vue";
import { answerPersonalTrainingItem, readPersonalTraining, readPersonalTrainingReport, savePersonalTrainingDraft, transitionPersonalTraining, type PersonalTrainingReport, type PersonalTrainingView } from "../api/personalTrainings";
import { fetchKnowledgeTree } from "../api/study";
import type { KnowledgeNodeView, PlanItemView } from "../types/practice";

const props = defineProps<{ trainingId: string; ownerSessionId: string }>();
const emit = defineEmits<{ ready: [available: boolean]; returnToday: [] }>();

const loading = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const training = ref<PersonalTrainingView | null>(null);
const report = ref<PersonalTrainingReport | null>(null);
const viewMode = ref<"focus" | "paper">("focus");
const focusItemId = ref("");
const answers = ref<Record<string, string>>({});
const notices = ref<Record<string, string>>({});
const revisions = new Map<string, number>();
const timers = new Map<string, number>();
const saves = new Map<string, Promise<void>>();
const dirtyDrafts = new Set<string>();
const answerKeys = new Map<string, { fingerprint: string; key: string }>();
const names = ref<Record<string, string>>({});
let loadToken = 0;

function walk(nodes: KnowledgeNodeView[]): void {
  for (const node of nodes) {
    names.value[node.id] = node.name;
    walk(node.children ?? []);
  }
}

function restoreDrafts(value: PersonalTrainingView): void {
  for (const item of value.items) {
    revisions.set(item.item_id, item.draft_revision ?? 0);
    if (item.completed) {
      dirtyDrafts.delete(item.item_id);
      notices.value[item.item_id] = item.latest_result === "right" ? "本专项答案已提交：正确。此结果只属于专项训练。"
        : item.latest_result === "wrong" ? "本专项答案已提交：需要复习。此结果只属于专项训练。"
        : "本专项答案已提交，判定结果待核验。此结果只属于专项训练。";
      continue;
    }
    const saved = item.options ? item.draft_selected_option : item.draft_answer;
    if (saved !== null && saved !== undefined) answers.value[item.item_id] = saved;
    else if (!(item.item_id in answers.value)) answers.value[item.item_id] = "";
  }
  if (!value.items.some((item) => item.item_id === focusItemId.value)) {
    focusItemId.value = value.items.find((item) => !item.completed)?.item_id ?? value.items[0]?.item_id ?? "";
  }
}

async function load(): Promise<void> {
  const token = ++loadToken;
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (!props.trainingId || !props.ownerSessionId) throw new Error("专项入口缺少有效身份，请从奶蛙聊天记录重新打开。 ");
    const value = await readPersonalTraining(props.trainingId, props.ownerSessionId);
    if (token !== loadToken) return;
    if (value.training_id !== props.trainingId || value.owner_session_id !== props.ownerSessionId) {
      throw new Error("专项身份与当前入口不一致，未加载其他训练数据。");
    }
    training.value = value;
    restoreDrafts(value);
    if (value.status === "completed") {
      try {
        const completedReport = await readPersonalTrainingReport(value.training_id, props.ownerSessionId);
        if (token !== loadToken) return;
        report.value = completedReport;
      } catch {
        if (token !== loadToken) return;
        report.value = null;
      }
    } else report.value = null;
    try {
      const tree = await fetchKnowledgeTree();
      if (token !== loadToken) return;
      walk(tree.nodes);
    } catch {
      if (token !== loadToken) return;
      /* the saved IDs and questions remain authoritative */
    }
    if (token !== loadToken) return;
    emit("ready", true);
  } catch (cause) {
    if (token !== loadToken) return;
    training.value = null;
    report.value = null;
    error.value = cause instanceof Error ? cause.message : "专项暂时无法读取，请从奶蛙聊天记录重新打开。";
    emit("ready", false);
  } finally {
    if (token === loadToken) loading.value = false;
  }
}

function persistDraft(itemId: string): Promise<void> {
  const prior = saves.get(itemId) ?? Promise.resolve();
  const task = prior.catch(() => undefined).then(async () => {
    const current = training.value;
    const item = current?.items.find((row) => row.item_id === itemId);
    if (!current || current.status !== "active" || !item || item.completed) {
      dirtyDrafts.delete(itemId);
      return;
    }
    const value = answers.value[itemId] ?? "";
    const updated = await savePersonalTrainingDraft(current.training_id, itemId, {
      owner_session_id: props.ownerSessionId,
      expected_draft_revision: revisions.get(itemId) ?? item.draft_revision ?? 0,
      draft_answer: item.options ? null : value,
      draft_selected_option: item.options ? value : null,
    });
    const savedItem = updated.items.find((row) => row.item_id === itemId);
    if (savedItem) revisions.set(itemId, savedItem.draft_revision);
    if ((answers.value[itemId] ?? "") === value && training.value?.training_id === updated.training_id) {
      training.value = updated;
      dirtyDrafts.delete(itemId);
    }
  }).catch((cause: unknown) => {
    error.value = cause instanceof Error ? cause.message : "答案草稿保存失败；正式答案尚未提交。";
    throw cause;
  });
  saves.set(itemId, task);
  void task.then(
    () => { if (saves.get(itemId) === task) saves.delete(itemId); },
    () => { if (saves.get(itemId) === task) saves.delete(itemId); },
  );
  return task;
}

function queueDraft(itemId: string): void {
  dirtyDrafts.add(itemId);
  const old = timers.get(itemId);
  if (old !== undefined) window.clearTimeout(old);
  timers.set(itemId, window.setTimeout(() => {
    timers.delete(itemId);
    void persistDraft(itemId).catch(() => undefined);
  }, 450));
}

async function flushDraft(itemId: string): Promise<void> {
  const timer = timers.get(itemId);
  if (timer !== undefined) { window.clearTimeout(timer); timers.delete(itemId); }
  const pending = saves.get(itemId);
  if (pending) {
    try { await pending; } catch { /* retry the still-dirty answer below */ }
  }
  if (dirtyDrafts.has(itemId)) await persistDraft(itemId);
}

async function flushAll(): Promise<void> {
  const itemIds = new Set([...dirtyDrafts, ...timers.keys(), ...saves.keys()]);
  await Promise.all([...itemIds].map(flushDraft));
}

function makeAnswerKey(itemId: string, version: number, raw: string, option: string): string {
  const fingerprint = JSON.stringify([version, raw, option]);
  const prior = answerKeys.get(itemId);
  if (prior?.fingerprint === fingerprint) return prior.key;
  const key = `training-answer-${crypto.randomUUID()}`;
  answerKeys.set(itemId, { fingerprint, key });
  return key;
}

const paperItems = computed<PlanItemView[]>(() => (training.value?.items ?? []).map((item) => ({
  id: item.item_id,
  ordinal: item.ordinal,
  display_number: item.ordinal,
  kp_id: item.kp_id,
  kp_name: names.value[item.kp_id] ?? "专项知识点",
  question_id: item.question_id,
  question_version_id: item.question_version_id,
  question_type: item.question_type,
  question_role: "typical",
  difficulty: item.difficulty,
  stem: item.stem,
  options: item.options,
  skill_tags: [],
  is_variant: false,
  estimated_minutes: item.estimated_minutes,
  completed: item.completed,
  completed_at: item.completed_at,
  latest_self_grade: null,
  is_review: false,
  is_external_reference: false,
  exam_reference: null,
})));
const completedCount = computed(() => paperItems.value.filter((item) => item.completed).length);
const currentIndex = computed(() => paperItems.value.findIndex((item) => item.id === focusItemId.value));
const currentItem = computed(() => paperItems.value[currentIndex.value] ?? paperItems.value[0] ?? null);
const kpNames = computed(() => [...new Set((training.value?.knowledge_point_ids ?? []).map((id) => names.value[id] ?? "专项知识点"))]);

async function submit(item: PlanItemView | null): Promise<void> {
  const current = training.value;
  if (!current || !item || current.status !== "active" || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await flushDraft(item.id);
    const latest = training.value;
    const question = latest?.items.find((row) => row.item_id === item.id);
    if (!latest || !question || question.completed) return;
    const value = answers.value[item.id] ?? "";
    const option = question.options ? value : "";
    const raw = question.options ? "" : value;
    training.value = await answerPersonalTrainingItem(latest.training_id, item.id, {
      owner_session_id: props.ownerSessionId,
      idempotency_key: makeAnswerKey(item.id, latest.version, raw, option),
      expected_version: latest.version,
      raw_answer: question.options ? null : raw,
      selected_option: question.options ? option : null,
    });
    const result = training.value.items.find((row) => row.item_id === item.id)?.latest_result;
    notices.value[item.id] = result === "right" ? "本专项答案已提交：正确。此结果只属于专项训练。"
      : result === "wrong" ? "本专项答案已提交：需要复习。此结果只属于专项训练。"
      : "本专项答案已提交，判定结果待核验。此结果只属于专项训练。";
    report.value = null;
    restoreDrafts(training.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "答案草稿未能保存，正式答案尚未提交。";
  } finally { busy.value = false; }
}

function changeItem(direction: -1 | 1): void {
  const next = paperItems.value[currentIndex.value + direction];
  if (next) focusItemId.value = next.id;
}

async function transition(action: "pause" | "resume" | "finish"): Promise<void> {
  const current = training.value;
  if (!current || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await flushAll();
    const latest = training.value;
    if (!latest || latest.training_id !== current.training_id) throw new Error("专项已切换，请重新读取后再操作。");
    training.value = await transitionPersonalTraining(current.training_id, action, {
      owner_session_id: props.ownerSessionId,
      request_key: `training-${action}-${crypto.randomUUID()}`,
      expected_version: latest.version,
    });
    notice.value = action === "pause" ? "专项已暂停，进度已保留。"
      : action === "resume" ? "专项已继续。"
      : "专项已结束，今日正式卷未改变。";
    if (action === "finish") report.value = await readPersonalTrainingReport(current.training_id, props.ownerSessionId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "专项状态更新失败，请重新读取。";
  } finally { busy.value = false; }
}

async function returnToToday(): Promise<void> {
  if (!training.value) { emit("returnToday"); return; }
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await flushAll();
    emit("returnToday");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "答案草稿尚未保存，暂时无法离开专项。";
  } finally { busy.value = false; }
}

watch(() => [props.trainingId, props.ownerSessionId], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => { void flushAll().catch(() => undefined); });
</script>

<template>
  <section class="personal-training-mode" data-testid="personal-training-mode" aria-label="专项练习模式">
    <p v-if="loading" role="status">正在读取专项练习…</p>
    <div v-else-if="error && !training" class="training-error" role="alert">
      <p>{{ error }}</p><button type="button" @click="emit('returnToday')">返回今日学习</button>
    </div>
    <template v-else-if="training">
      <header class="training-heading">
        <div><p class="eyebrow">独立专项练习</p><h2>{{ training.title }}</h2>
          <p>{{ kpNames.join("、") || "按专项题目范围练习" }}</p>
          <p class="training-facts">{{ paperItems.length }} 道 · 预计 {{ training.actual_minutes }} 分钟 / 目标 {{ training.target_minutes }} 分钟 · {{ completedCount }}/{{ paperItems.length }} 完成</p>
        </div>
        <div class="training-heading-actions">
          <span :data-status="training.status">{{ training.status === "active" ? "进行中" : training.status === "paused" ? "已暂停" : training.status === "completed" ? "已完成" : "已取消" }}</span>
          <RouterLink :to="{ path: '/chat', query: { session_id: ownerSessionId } }">回奶蛙聊天</RouterLink>
          <button type="button" :disabled="busy" data-testid="return-today-mode" @click="returnToToday">返回今日学习</button>
        </div>
      </header>
      <StudyProgressSummary :completed="completedCount" :total="paperItems.length" label="专项完成进度" accessible-label="专项练习完成进度" test-id="training-progress-summary" />
      <p v-if="error" class="training-error" role="alert">{{ error }}</p>
      <p v-if="notice" role="status">{{ notice }}</p>
      <div class="training-actions">
        <button v-if="training.status === 'active'" type="button" :disabled="busy" data-testid="pause-training" @click="transition('pause')">暂停专项</button>
        <button v-else-if="training.status === 'paused'" type="button" :disabled="busy" data-testid="resume-training" @click="transition('resume')">继续专项</button>
        <button v-if="training.status === 'active' || training.status === 'paused'" type="button" :disabled="busy" data-testid="finish-training" @click="transition('finish')">结束专项</button>
      </div>
      <nav class="study-modes" aria-label="专项答题方式">
        <button type="button" :class="{ active: viewMode === 'focus' }" data-testid="training-focus-mode" @click="viewMode = 'focus'">专注模式</button>
        <button type="button" :class="{ active: viewMode === 'paper' }" data-testid="training-full-paper" @click="viewMode = 'paper'">预览全卷</button>
      </nav>
      <section v-if="viewMode === 'focus'" class="training-focus">
        <StudyFocus :item="currentItem" :answer-open="false" :answer-loading="false" :answer-error="null"
          :submitting="busy" :read-only="training.status !== 'active'" :show-answer-reveal="false"
          :allow-self-report="false" :has-previous="currentIndex > 0" :has-next="currentIndex >= 0 && currentIndex < paperItems.length - 1"
          :display-number="Math.max(1, currentIndex + 1)" :raw-answer="currentItem ? (currentItem.options ? '' : answers[currentItem.id] ?? '') : ''"
          :selected-option="currentItem?.options ? answers[currentItem.id] : undefined"
          :notice="currentItem ? notices[currentItem.id] : ''" empty-title="专项还没有分配题目" empty-message="可以回到奶蛙聊天继续调整这个专项。"
          @submit-answer="submit(currentItem)" @continue="changeItem(1)" @previous="changeItem(-1)"
          @update:raw-answer="(value: string) => currentItem && (answers[currentItem.id] = value, queueDraft(currentItem.id))"
          @update:selected-option="(value: string) => currentItem && (answers[currentItem.id] = value, queueDraft(currentItem.id))" />
      </section>
      <StudyPaperPreview v-else :items="paperItems" test-id="training-paper-list">
        <template #item="{ item, index }">
          <header><strong>第 {{ index + 1 }} 题</strong><span>{{ item.question_type }}</span><span>{{ item.completed ? "已提交" : "未完成" }}</span></header>
          <MarkdownContent class="training-stem" :text="item.stem ?? ''" />
          <div class="training-paper-actions"><small>{{ item.kp_name }} · {{ item.difficulty }} · {{ item.estimated_minutes }} 分钟</small>
            <button type="button" data-testid="training-focus-item" @click="focusItemId = item.id; viewMode = 'focus'">{{ item.completed ? "查看作答记录" : "逐题作答" }}</button>
          </div>
        </template>
      </StudyPaperPreview>
      <section v-if="report" class="training-report" data-testid="personal-training-report">
        <h3>专项报告</h3><p>已提交 {{ report.submitted_count }} 题，正确 {{ report.right_count }} 题，需复习 {{ report.wrong_count }} 题。</p>
        <ul v-if="report.wrong_knowledge_points.length"><li v-for="kp in report.wrong_knowledge_points" :key="kp.kp_id">{{ kp.name }}：{{ kp.wrong_count }} 次错误</li></ul>
        <p v-else>本次没有记录到错误知识点。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.personal-training-mode{max-width:1240px;margin:0 auto;padding:28px clamp(16px,4vw,48px) 56px;color:#344338}.training-heading{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;border-bottom:1px solid #e4e8dd;padding-bottom:18px}.training-heading h2{margin:5px 0;font-size:28px}.training-heading p{margin:4px 0;color:#758171}.eyebrow{font-size:12px;letter-spacing:.08em}.training-facts{font-size:13px}.training-heading-actions{display:flex;gap:10px;align-items:center}.training-heading-actions a{padding:7px 10px;color:#415345;text-decoration:none;border:1px solid #d6dfd0;border-radius:9px;background:#fff}.training-heading button,.training-actions button,.study-modes button,.training-paper-actions button,.training-error button{min-height:38px;padding:7px 12px;border:1px solid #d6dfd0;border-radius:9px;background:#fff;color:#415345;cursor:pointer}.training-actions,.study-modes{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.study-modes .active{background:#4c6d58;color:#fff}.training-focus{min-width:0}.training-error{padding:12px;border-radius:10px;background:#fff2ed;color:#9b4937}.training-stem{line-height:1.7}.training-stem :deep(p){margin:0 0 14px}.training-paper-actions{display:flex;justify-content:flex-end;gap:10px;align-items:center;margin-top:12px}.training-paper-actions small{margin-right:auto;color:#778273}.training-report{margin-top:24px;padding:16px;border-radius:12px;background:#f3f5ed}.training-report h3{margin-top:0}@media(max-width:640px){.training-heading{flex-direction:column}.training-heading-actions{width:100%;justify-content:space-between}.personal-training-mode{padding:18px 12px 36px}.training-paper-actions{align-items:flex-start;flex-direction:column}}
</style>
