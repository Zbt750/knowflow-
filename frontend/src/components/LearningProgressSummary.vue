<script setup lang="ts">
import type { components } from "../api/types";
defineProps<{ progress: components["schemas"]["LearningProgress"]; lessonTo?: string }>();
</script>

<template>
  <section class="learning-progress" aria-label="学习进展" data-testid="learning-progress" :data-status="progress.status">
    <strong data-testid="learning-progress-label">{{ progress.label }}</strong>
    <p>{{ progress.reason }}</p>
    <p class="next-step" data-testid="learning-progress-next-step">{{ progress.next_step }}</p>
    <p class="reliability">{{ progress.reliability_note }}</p>
    <RouterLink v-if="lessonTo && ['read_lesson', 'consolidate'].includes(progress.next_action)" :to="lessonTo">阅读讲解 →</RouterLink>
    <RouterLink v-else to="/study">去今日学习安排练习 →</RouterLink>
    <details v-if="progress.limitations?.length">
      <summary>查看反馈依据与限制</summary>
      <p v-for="note in progress.limitations ?? []" :key="note">{{ note }}</p>
    </details>
  </section>
</template>

<style scoped>
.learning-progress { padding: 12px 0 18px; }
strong { font-size: 17px; font-weight: 600; color: var(--text-primary); }
p { margin: 7px 0; line-height: 1.65; font-size: 13px; color: var(--text-secondary); }
.reliability, details p { color: var(--text-tertiary); font-size: 12px; }
a { display: inline-block; margin-top: 5px; font-size: 12px; color: var(--text-secondary); }
details { margin-top: 10px; }
summary { cursor: pointer; font-size: 12px; color: var(--text-tertiary); }
</style>
