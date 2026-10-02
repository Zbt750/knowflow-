<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { confirmLearningTask } from "../api/learningTasks";
import { useRouter } from "vue-router";
import { createLearningTask, fetchLearningTask, runLearningTask, cancelLearningTask, modifyLearningTask, type LearningTask } from "../api/learningTasks";

const props = defineProps<{ sessionId: string | null }>();
const router = useRouter();
const task = ref<LearningTask | null>(null);
const goal = ref("");
const budget = ref(90);
const busy = ref(false);
const error = ref("");
const refreshing = ref(false);
const savedTaskId = ref<string | null>(null);
let epoch = 0;
let poll: ReturnType<typeof setTimeout> | undefined;
let pollGeneration = 0;
const labels: Record<string, string> = { search_knowledge: "定位知识范围", get_learning_state: "查看学习记录", find_questions: "查找真实题目", read_lesson: "读取知识讲解", validate_plan: "检查题目与时长" };
const statusLabels: Record<string, string> = { created: "等待安排", running: "正在安排", ready: "草案已校验", needs_info: "需要补充信息", failed: "本次未完成", cancelled: "已取消" };
const storageKey = () => `learning-task:${props.sessionId ?? "builtin-draft"}`;
function stopPoll() { ++pollGeneration; if (poll) clearTimeout(poll); poll = undefined; }
function remember(id: string) { savedTaskId.value = id; try { localStorage.setItem(storageKey(), id); } catch { /* storage optional */ } }

watch(() => props.sessionId, async () => {
  const active = ++epoch;
  stopPoll(); busy.value = false; refreshing.value = false; savedTaskId.value = null; task.value = null; goal.value = ""; error.value = "";
  let saved: string | null = null;
  try { saved = localStorage.getItem(storageKey()); } catch { /* storage optional */ }
  if (!saved) return;
  savedTaskId.value = saved;
  try {
    const restored = await fetchLearningTask(saved);
    if (active !== epoch) return;
    task.value = restored; goal.value = restored.goal; budget.value = restored.budget_minutes;
    if (restored.status === "running") startPoll(saved, active);
  } catch { if (active === epoch) error.value = "上次学习任务暂时无法读取，请刷新状态后检查。"; }
}, { immediate: true });

function startPoll(id: string, active: number) {
  stopPoll();
  const generation = pollGeneration;
  let failures = 0;
  const tick = async () => {
    try {
      const updated = await fetchLearningTask(id);
      if (active !== epoch || generation !== pollGeneration) return;
      failures = 0;
      task.value = updated;
      if (updated.status !== "running") { stopPoll(); return; }
    } catch {
      if (active !== epoch || generation !== pollGeneration) return;
      if (++failures >= 3) {
        stopPoll(); error.value = "暂时无法读取进度，请刷新任务状态；不会重新运行模型。"; return;
      }
    }
    if (active === epoch && generation === pollGeneration) poll = setTimeout(tick, 1500);
  };
  poll = setTimeout(tick, 1500);
}

// Only read the persisted task: never rerun the model or replace unsaved form edits.
async function refreshTask(active = epoch) {
  const id = task.value?.task_id ?? savedTaskId.value;
  if (!id || refreshing.value) return false;
  stopPoll(); refreshing.value = true;
  try {
    const updated = await fetchLearningTask(id);
    if (active !== epoch) return false;
    if (!task.value && !goal.value.trim()) { goal.value = updated.goal; budget.value = updated.budget_minutes; }
    task.value = updated; error.value = "";
    if (updated.status === "running") startPoll(id, active);
    return true;
  } catch {
    if (active === epoch) error.value = "任务状态暂时无法读取，请稍后刷新；已输入的目标和草案会保留。";
    return false;
  } finally { if (active === epoch) refreshing.value = false; }
}

async function arrange(fresh = false) {
  if (busy.value || refreshing.value || !goal.value.trim() || !Number.isInteger(budget.value) || budget.value < 5 || budget.value > 240) return;
  const active = ++epoch;
  busy.value = true; error.value = "";
  try {
    const created = !task.value || fresh
      ? await createLearningTask(goal.value.trim(), budget.value, props.sessionId)
      : task.value.metrics.commit
        ? await createLearningTask(goal.value.trim(), budget.value, props.sessionId)
        : await modifyLearningTask(task.value.task_id, goal.value.trim(), budget.value);
    if (active !== epoch) return;
    task.value = created; remember(created.task_id);
    startPoll(created.task_id, active);
    const result = await runLearningTask(created.task_id);
    if (active === epoch) { stopPoll(); task.value = result; }
  } catch (cause) {
    if (active === epoch) {
      error.value = cause instanceof Error ? cause.message : "安排未完成，可重试。";
      if (task.value) await refreshTask(active);
    }
  } finally {
    if (active === epoch) busy.value = false;
  }
}

async function cancel() {
  if (!task.value) return;
  const active = epoch;
  try {
    const cancelled = await cancelLearningTask(task.value.task_id);
    if (active === epoch) { ++epoch; task.value = cancelled; busy.value = false; refreshing.value = false; stopPoll(); }
  } catch { if (active === epoch) error.value = "取消未确认，请刷新任务状态。"; }
}
async function confirm() {
  if (!task.value?.draft_version || busy.value || refreshing.value) return;
  const active = epoch;
  busy.value = true; error.value = "";
  try {
    const result = await confirmLearningTask(task.value.task_id, task.value.draft_version);
    if (active === epoch) task.value = result;
  } catch (cause) {
    if (active === epoch) {
      const message = cause instanceof Error ? cause.message : "确认未完成";
      await refreshTask(active);
      if (active === epoch && !task.value?.metrics.commit) error.value = `${message}。请检查任务状态后再确认。`;
    }
  } finally { if (active === epoch) busy.value = false; }
}
onBeforeUnmount(() => { ++epoch; stopPoll(); });
</script>

<template>
  <details class="learning-task" data-testid="learning-task-panel">
    <summary>安排学习 <span>本次学习草案</span></summary>
    <div class="task-content">
      <label>学习目标<textarea v-model="goal" rows="2" maxlength="1200" placeholder="例如：积分比较弱，帮我找适合的题，安排本次复习" data-testid="task-goal" :disabled="busy || task?.status === 'running'"></textarea></label>
      <div class="task-controls">
        <label>本次时间 <input v-model.number="budget" type="number" min="5" max="240" :disabled="busy || task?.status === 'running'" data-testid="task-budget" /> 分钟</label>
        <button type="button" :disabled="busy || refreshing || task?.status === 'running' || goal.trim().length < 2 || !Number.isInteger(budget) || budget < 5 || budget > 240" data-testid="task-arrange" @click="arrange()">{{ busy ? '正在安排…' : task ? '修改并重新安排' : '生成草案' }}</button>
        <button v-if="task && !busy && task.status !== 'running'" type="button" :disabled="refreshing" @click="arrange(true)">新任务</button>
        <button v-if="task || savedTaskId" type="button" data-testid="task-refresh" :disabled="busy || refreshing" @click="refreshTask()">{{ refreshing ? '正在读取…' : '刷新状态' }}</button>
        <button v-if="task && task.status !== 'cancelled' && !task.metrics.commit" type="button" data-testid="task-cancel" @click="cancel">取消</button>
      </div>
      <p class="task-note">先生成并检查草案，不会自动添加题目，也不会改变掌握度。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <section v-if="task" aria-live="polite" data-testid="task-result">
        <p>{{ task.metrics.commit ? '已加入今日学习' : statusLabels[task.status] }} · {{ task.message }}</p>
        <ul v-if="task.trace.length" class="task-steps"><li v-for="(step, index) in task.trace" :key="index">{{ labels[String(step.tool)] ?? '检查任务' }}{{ step.status === 'error' ? ' · 需调整' : ' · 完成' }}</li></ul>
        <div v-if="task.draft && task.status === 'ready'" class="task-draft">
          <p>预计 {{ task.draft.total_minutes }} / {{ task.budget_minutes }} 分钟</p>
          <p v-if="task.draft.review_minutes">知识复习 {{ task.draft.review_minutes }} 分钟：{{ (task.draft.review_nodes as Array<{name: string}>).map(n => n.name).join('、') }}</p>
          <ol><li v-for="q in (task.draft.questions as Array<{question_id: string; stem: string; minutes: number}>)" :key="q.question_id">{{ q.stem }} <span>{{ q.minutes }} 分钟</span></li></ol>
          <p>{{ task.draft.rationale }}</p>
          <p v-for="warning in (task.draft.warnings as string[])" :key="warning" class="task-note">{{ warning }}</p>
          <template v-if="task.metrics.commit">
            <p class="task-note">题目已加入今日学习；知识复习可按此草案进行。</p>
            <button type="button" @click="router.push('/study')">去做题</button>
          </template>
          <template v-else>
            <p class="task-note">尚未加入今日学习，确认后只添加题目，不改变掌握度。</p>
            <button v-if="(task.draft.questions as unknown[]).length" type="button" data-testid="task-confirm" :disabled="busy || refreshing || goal.trim() !== task.goal || budget !== task.budget_minutes" @click="confirm">{{ busy ? '正在确认…' : '确认加入今日学习' }}</button>
          </template>
        </div>
      </section>
    </div>
  </details>
</template>

<style scoped>
.learning-task { flex: 0 0 auto; margin: 0 24px; border-bottom: 1px solid var(--border); color: var(--text-secondary); font-size: 13px; }
summary { cursor: pointer; padding: 9px 0; width: fit-content; }
summary span, .task-note, .task-draft li span { color: var(--text-tertiary); font-size: 12px; }
.task-content { max-height: 36vh; overflow-y: auto; padding: 4px 0 14px; }
textarea { width: 100%; min-height: 56px; border-radius: 10px; margin: 5px 0 9px; resize: vertical; }
.task-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
input { width: 76px; padding: 5px 8px; border-radius: 8px; }
button { padding: 6px 10px; border-radius: 8px; }
.task-steps { display: flex; flex-wrap: wrap; gap: 5px 16px; list-style: none; padding: 0; font-size: 12px; }
.task-draft ol { padding-left: 22px; }
.task-draft li { margin: 8px 0; }
@media (max-width: 600px) { .learning-task { margin: 0 12px; } }
</style>
