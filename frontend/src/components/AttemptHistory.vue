<script setup lang="ts">
import { ref, watch } from "vue";
import { fetchAnswerHistory } from "../api/study";
import type { components } from "../api/types";
import { attemptLabel } from "../lib/attemptSequence";
import { answerFeedback } from "../lib/answerFeedback";

const props = defineProps<{ itemId: string; latestAttemptId: string }>();
const history = ref<components["schemas"]["AnswerSubmissionHistory"] | null>(null);
const busy = ref(false);
const error = ref("");
const opened = ref(false);
let generation = 0;

async function load() {
  const token = ++generation;
  const id = props.itemId;
  busy.value = true; error.value = "";
  try {
    const result = await fetchAnswerHistory(id);
    if (token === generation) history.value = result;
  } catch {
    if (token === generation) error.value = "暂时无法读取作答记录";
  } finally {
    if (token === generation) busy.value = false;
  }
}
watch(() => [props.itemId, props.latestAttemptId], () => {
  ++generation; busy.value = false; history.value = null; error.value = "";
  if (opened.value) void load();
});
function toggle(event: Event) {
  opened.value = (event.target as HTMLDetailsElement).open;
  if (opened.value && !history.value && !busy.value) void load();
}
</script>

<template>
  <details class="attempt-history" :data-testid="`attempt-history-${itemId}`" @toggle="toggle">
    <summary>作答记录</summary>
    <p v-if="busy" role="status">正在读取…</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" :disabled="busy" @click="load">重试</button></p>
    <ol v-if="history">
      <li v-for="(attempt, index) in history.items" :key="attempt.attempt_id">
        <span>第 {{ attempt.attempt_number ?? index + 1 }} 次</span>
        <span :aria-label="answerFeedback(attempt).label">{{ answerFeedback(attempt).symbol }}</span>
        <span>{{ attemptLabel(attempt) }}</span>
        <pre>{{ attempt.selected_option || attempt.raw_answer || '（未填写）' }}</pre>
      </li>
    </ol>
    <p v-if="history?.legacy_self_report_count">另有 {{ history.legacy_self_report_count }} 条旧自述记录，不当作机器判题。</p>
  </details>
</template>

<style scoped>
.attempt-history { margin-top: 18px; color: var(--text-secondary); font-size: 12px; }
summary { cursor: pointer; width: fit-content; }
ol { padding-left: 18px; margin-top: 10px; }
li { margin: 9px 0; }
li > span { margin-right: 10px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; color: var(--text-tertiary); margin: 4px 0; }
</style>
