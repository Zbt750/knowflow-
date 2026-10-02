<script setup lang="ts">
import { toRef } from "vue";
import { fetchLatestProcessReview, reviewProcess, type ProcessReviewState } from "../api/study";
import MarkdownContent from "./MarkdownContent.vue";
import PhotoTranscription from "./PhotoTranscription.vue";
const props = defineProps<{ itemId: string; questionType: string; modelValue: string; state: ProcessReviewState }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
// 状态由页面持有，切换专注/整卷不丢失进行中的请求或重试键。
const result = toRef(props.state, "result");
const busy = toRef(props.state, "busy");
const error = toRef(props.state, "error");
const kind = toRef(props.state, "kind");
async function restore(event: Event) {
  if (!(event.target as HTMLDetailsElement).open || props.state.loaded || busy.value) return;
  await reloadLatest();
}
async function reloadLatest() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { result.value = await fetchLatestProcessReview(props.itemId); props.state.loaded = true; }
  catch { error.value = "暂时无法读取上次建议，可以重试。"; }
  finally { busy.value = false; }
}
async function submit() {
  if (busy.value) return;
  const text = props.modelValue.trim();
  if (text.length < 10) { error.value = "请写至少 10 个字的过程或伪代码。"; return; }
  const signature = JSON.stringify([text, kind.value]);
  if (signature !== props.state.previous) { props.state.previous = signature; props.state.requestKey = crypto.randomUUID(); }
  busy.value = true; error.value = "";
  try { result.value = await reviewProcess(props.itemId, text, props.state.requestKey, props.questionType === "subjective" ? kind.value : undefined); props.state.loaded = true; }
  catch (e) { error.value = e instanceof Error ? e.message : "审阅失败，请重试。"; }
  finally { busy.value = false; }
}
</script>
<template>
  <details class="process-review" @toggle="restore">
    <summary>检查我的过程</summary>
    <p class="hint">文字或伪代码将发送给当前模型。建议仅供核对，不是正式判分；使用后不计独立作答证据。</p>
    <PhotoTranscription :item-id="itemId" :disabled="busy" :has-text="Boolean(modelValue.trim())" @apply="emit('update:modelValue', $event)" />
    <label v-if="questionType === 'subjective'">内容类型
      <select v-model="kind" :disabled="busy"><option value="concept">概念与讨论</option><option value="algorithm">算法与伪代码</option></select>
    </label>
    <textarea :value="modelValue" maxlength="4000" rows="4" aria-label="解题过程或伪代码" :disabled="busy" placeholder="仍可以在纸上做题，只录入需要核对的关键步骤。" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" />
    <button type="button" :disabled="busy" @click="submit">{{ busy ? '处理中…' : '获取辅助建议' }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" type="button" :disabled="busy" @click="reloadLatest">读取最新建议</button>
    <div v-if="result" aria-live="polite"><MarkdownContent :text="result.feedback" /></div>
  </details>
</template>
<style scoped>
.process-review { margin-top: 24px; color: var(--text-secondary); }
summary { cursor: pointer; font-size: 13px; width: fit-content; }
.hint { font-size: 12px; line-height: 1.6; color: var(--text-tertiary); }
textarea { display: block; width: 100%; margin: 12px 0; resize: vertical; border-radius: 12px; }
label { font-size: 12px; }
</style>
