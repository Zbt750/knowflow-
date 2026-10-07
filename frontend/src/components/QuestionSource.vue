<script setup lang="ts">
import type { QuestionSourceView } from "../types/practice";
import { questionSourceLabel } from "../lib/questionSource";
withDefaults(defineProps<{ source?: QuestionSourceView | null; showOriginalNumber?: boolean }>(), { showOriginalNumber: true });
</script>

<template>
  <p class="question-source" data-testid="question-source" :title="source?.paper_title ?? undefined">{{ questionSourceLabel(source, showOriginalNumber) }}</p>
</template>

<style scoped>
.question-source { color: #68717d; font-size: 13px; line-height: 1.6; margin: 8px 0 16px; overflow-wrap: anywhere; }
</style>
