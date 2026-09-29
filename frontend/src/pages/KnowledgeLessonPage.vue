<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute } from "vue-router";

import { fetchKnowledgeLesson } from "../api/study";
import MarkdownContent from "../components/MarkdownContent.vue";
import { StaleResponse, useAsyncTask } from "../composables/useAsyncTask";
import type { KnowledgeLessonResponse } from "../types/practice";

const route = useRoute();
const lessonTask = useAsyncTask<KnowledgeLessonResponse>(null, {
  errorMessages: {
    knowledge_point_not_found: "知识点不存在，请从知识树重新选择。",
    knowledge_lesson_not_found: "这篇系统讲解尚未提供。",
  },
  fallbackMessage: "加载系统讲解失败",
});
const lesson = computed(() => lessonTask.data.value);
const state = computed(() => lessonTask.state.value);
const errorMessage = computed(() => lessonTask.errorMessage.value);
let requestToken = 0;

async function load(code: string): Promise<void> {
  const token = ++requestToken;
  lessonTask.reset();
  await lessonTask.run(async () => {
    const data = await fetchKnowledgeLesson(code);
    if (token !== requestToken) throw new StaleResponse();
    return data;
  });
}

watch(
  () => route.params.code,
  (value) => void load(typeof value === "string" ? value : ""),
  { immediate: true },
);
watch(lesson, (value) => {
  if (value) document.title = value.name + " · 考研知识库";
});
</script>

<template>
  <section class="page lesson-page" data-testid="knowledge-lesson-page">
    <RouterLink class="lesson-back" :to="{ path: '/knowledge', query: lesson ? { node: lesson.code } : {} }">
      ← 返回知识树
    </RouterLink>

    <p v-if="state === 'loading'" class="state state--loading">正在加载系统讲解…</p>
    <div v-else-if="state === 'error'" class="state state--error" data-testid="lesson-error">
      <p>{{ errorMessage }}</p>
      <button type="button" @click="load(String(route.params.code ?? ''))">重试</button>
    </div>
    <template v-else-if="lesson">
      <nav class="lesson-crumbs" aria-label="知识章节路径">
        <template v-for="(part, index) in lesson.breadcrumbs" :key="part.code">
          <span v-if="index > 0" aria-hidden="true">/</span>
          <span v-if="index === lesson.breadcrumbs.length - 1" aria-current="page">{{ part.name }}</span>
          <RouterLink v-else :to="'/knowledge/' + encodeURIComponent(part.code) + '/lesson'">{{ part.name }}</RouterLink>
        </template>
      </nav>
      <p class="lesson-source">{{ lesson.is_assessable ? "系统讲解" : "章节导读" }} · {{ lesson.subject }}</p>
      <article class="lesson-article" data-testid="lesson-article">
        <MarkdownContent :text="lesson.markdown" />
      </article>
      <footer v-if="lesson.is_assessable" class="lesson-next">
        <p>读完后可以独立复做例题，再去题库检验理解。</p>
        <div class="lesson-next-actions">
          <RouterLink :to="{ path: '/knowledge', query: { node: lesson.code, tab: 'questions' } }">
            查看相关题目（{{ lesson.question_count }}）
          </RouterLink>
          <RouterLink :to="{ path: '/study', query: { kp_id: lesson.id } }">
            去今日学习选题
          </RouterLink>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.lesson-page { width: min(940px, 100%); margin: 0 auto; padding: 26px clamp(18px, 4vw, 60px) 70px; }
.lesson-back { display: inline-flex; align-items: center; color: var(--text-secondary); font-size: 13px; text-decoration: none; }
.lesson-back:hover { color: var(--text); }
.lesson-crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 30px; color: var(--text-secondary); font-size: 12px; }
.lesson-crumbs a { color: inherit; text-decoration: none; }
.lesson-crumbs a:hover { text-decoration: underline; }
.lesson-crumbs [aria-current="page"] { color: var(--text); }
.lesson-source { margin: 18px 0 0; color: var(--text-secondary); font-size: 12px; }
.lesson-article { max-width: 760px; padding-top: 3px; font-size: 15px; line-height: 1.9; }
.lesson-article :deep(.markdown-content > h1) { margin: 8px 0 24px; font-size: clamp(27px, 3vw, 34px); line-height: 1.3; }
.lesson-article :deep(.markdown-content > h2) { margin-top: 35px; padding-top: 7px; font-size: 19px; }
.lesson-article :deep(.markdown-content > p) { margin-bottom: 15px; }
.lesson-next { max-width: 760px; margin-top: 38px; padding-top: 20px; border-top: 1px solid var(--border); }
.lesson-next > p { color: var(--text-secondary); font-size: 13px; }
.lesson-next-actions { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 13px; }
.lesson-next-actions a { color: #245c9d; font-size: 14px; text-decoration: none; }
.lesson-next-actions a:hover { text-decoration: underline; }
@media (max-width: 620px) { .lesson-page { padding-top: 20px; } .lesson-crumbs { margin-top: 22px; } }
</style>
