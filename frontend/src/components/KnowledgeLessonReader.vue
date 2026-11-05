<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from "vue";
import { fetchKnowledgeLesson } from "../api/study";
import { StaleResponse, useAsyncTask } from "../composables/useAsyncTask";
import type { KnowledgeLessonResponse } from "../types/practice";
import MarkdownContent from "./MarkdownContent.vue";

const props = defineProps<{ code: string }>();
const task = useAsyncTask<KnowledgeLessonResponse>(null, { fallbackMessage: "加载知识讲解失败" });
const lesson = computed(() => task.data.value);
const state = computed(() => task.state.value);
const error = computed(() => task.errorMessage.value);
let generation = 0;
async function load() {
  const token = ++generation;
  const code = props.code;
  task.reset();
  await task.run(async () => {
    const result = await fetchKnowledgeLesson(code);
    if (token !== generation || code !== props.code) throw new StaleResponse();
    return result;
  });
}
watch(() => props.code, () => void load(), { immediate: true });
onBeforeUnmount(() => { generation += 1; task.reset(); });
</script>

<template>
  <section class="node-lesson" aria-label="知识讲解正文" data-testid="inline-knowledge-lesson">
    <p v-if="state === 'loading'" role="status">正在加载知识讲解…</p>
    <div v-else-if="state === 'error'" role="alert">
      <p>{{ error }}</p><button type="button" @click="load">重新加载讲解</button>
    </div>
    <MarkdownContent v-else-if="lesson" :text="lesson.markdown" />
  </section>
</template>

<style scoped>
.node-lesson { max-width: 780px; margin: 18px 0 30px; line-height: 1.85; }
.node-lesson :deep(h1) { font-size: 23px; margin: 12px 0 22px; }
.node-lesson :deep(h2) { font-size: 17px; margin-top: 28px; }
</style>
