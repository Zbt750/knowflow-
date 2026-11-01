<script setup lang="ts">
import type {DifficultySummary} from '../api/personalQuestions';
defineProps<{summary?:DifficultySummary|null}>();
</script>
<template>
  <section class="difficulty-summary" data-testid="generation-difficulty-summary" aria-label="练习难度说明">
    <template v-if="summary">
      <dl>
        <div><dt>目标难度</dt><dd>{{ summary.target_label }}</dd></div>
        <div><dt>预计实际 · 模型自评</dt><dd>{{ summary.estimated_label }}</dd></div>
        <div><dt>相对原题要求</dt><dd>{{ summary.relative_label }}</dd></div>
        <div><dt>相对变化 · 模型自评</dt><dd>{{ summary.relative_estimate }}</dd></div>
      </dl>
      <p v-if="summary.model_assessment">模型自评理由：{{ summary.model_assessment.reason }}</p>
      <small v-if="summary.target_basis==='relative_inferred'">目标等级由相对要求推定，不是对原题难度的独立测量。</small>
      <small>{{ summary.notice }}</small>
      <details v-if="summary.requirement.raw_text"><summary>查看原始出题要求</summary><p>{{ summary.requirement.raw_text }}</p></details>
    </template>
    <small v-else>旧记录未保存难度分析，无法确认实际难度或相对变化。</small>
  </section>
</template>
<style scoped>
.difficulty-summary{margin:10px 0 14px;padding:12px 14px;border:1px solid var(--border);border-radius:12px;background:var(--bg,#fafbf7);overflow-wrap:anywhere;min-width:0}
dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 16px;margin:0 0 10px}dt{font-size:11px;color:var(--text-secondary)}dd{margin:3px 0 0;font-size:13px;font-weight:600}p{margin:6px 0;font-size:13px;line-height:1.65}small{display:block;font-size:11px;color:var(--text-secondary);line-height:1.6}details{margin-top:7px;font-size:11px}details p{white-space:pre-wrap;font-size:12px}
@media(max-width:600px){dl{grid-template-columns:minmax(0,1fr)}.difficulty-summary{padding:10px}}
</style>
