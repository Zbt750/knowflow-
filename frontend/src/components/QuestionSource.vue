<script setup lang="ts">
import type { QuestionSourceView, QuestionTrustView } from "../types/practice";
import { questionSourceLabel } from "../lib/questionSource";
withDefaults(defineProps<{ source?: QuestionSourceView | null; trust?: QuestionTrustView | null; showOriginalNumber?: boolean; isVariant?: boolean }>(), { showOriginalNumber: true, isVariant: false });
</script>

<template>
  <p class="question-source" data-testid="question-source" :title="source?.paper_title ?? undefined">{{ questionSourceLabel(source, showOriginalNumber, trust, isVariant) }}</p>
</template>

<style scoped>
.question-source { display: inline-flex; width: fit-content; max-width: 100%; color: #687b5b; font-size: 11px; line-height: 1.45; margin: 7px 7px 8px 0; padding: 3px 8px; border: 1px solid #e0e6d8; border-radius: 999px; background: #f5f7ef; overflow-wrap: anywhere; }
</style>
