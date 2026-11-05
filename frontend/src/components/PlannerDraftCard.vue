<script setup lang="ts">
import { ref, watch } from "vue";
import { fetchLearningTask, confirmLearningTask, type LearningTask } from "../api/learningTasks";
const props = defineProps<{ taskId: string }>();
const emit = defineEmits<{ confirmed: []; explain: [task: LearningTask] }>();
const task = ref<LearningTask | null>(null), busy = ref(false), error = ref("");
let version = 0;
async function refresh() {
  const active = ++version;
  try { const value = await fetchLearningTask(props.taskId); if (active === version) { task.value = value; error.value = ""; } }
  catch { if (active === version) error.value = "暂时无法读取方案，请重试。"; }
}
watch(() => props.taskId, refresh, { immediate: true });
async function confirm() {
  if (!task.value?.draft_version || busy.value) return;
  busy.value = true;
  try { task.value = await confirmLearningTask(props.taskId, task.value.draft_version); emit("confirmed"); }
  catch { await refresh(); if (!task.value?.metrics.commit) error.value = "确认未完成，请检查方案状态后重试。"; }
  finally { busy.value = false; }
}
function groups(task: LearningTask) {
  const rows = (task.draft?.questions ?? []) as Array<{ kp_name: string; question_type: string }>;
  const counts = new Map<string, number>();
  for (const row of rows) { const key = `${row.kp_name} · ${{ single_choice: "选择题", fill_blank: "填空题", calculation: "计算题", proof: "证明题", discussion: "讨论题", program: "程序题" }[row.question_type] ?? "练习题"}`; counts.set(key, (counts.get(key) ?? 0) + 1); }
  return [...counts].map(([label, count]) => `${label} ${count} 道`);
}
</script>
<template>
  <div class="planner-card" data-testid="assistant-planner-card">
    <p v-if="error" role="alert">{{ error }} <button @click="refresh">读取状态</button></p>
    <template v-if="task?.draft">
      <p v-for="summary in groups(task)" :key="summary">{{ summary }}</p>
      <span v-if="task.metrics.commit">已加入今日学习</span>
      <button v-else-if="task.status === 'ready'" :disabled="busy" @click="confirm">{{ busy ? "正在确认…" : "确认加入今日学习" }}</button>
      <button @click="emit('explain', task)">先讲讲相关知识</button>
    </template>
  </div>
</template>
<style scoped>
.planner-card { margin-top: 8px; font-size: 13px; color: var(--text-secondary); }
.planner-card p { margin: 5px 0; }
.planner-card button { margin: 4px 8px 4px 0; border-radius: 8px; padding: 5px 10px; }
</style>
