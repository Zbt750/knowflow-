<script setup lang="ts">
import type {GenerationResult} from '../api/personalQuestions';
defineProps<{generation:GenerationResult}>();
</script>
<template>
  <div v-if="generation.outcome_summary" class="generation-outcome" data-testid="generation-outcome-summary" aria-label="本次出题结果统计">
    <p>请求 {{ generation.outcome_summary.requested_count }} 道 · 已保存 {{ generation.outcome_summary.saved_count }} 道 · 未保存 {{ generation.outcome_summary.failed_count }} 道</p>
    <small v-if="generation.outcome_summary.network_failed_count">模型网络请求失败 {{ generation.outcome_summary.network_failed_count }} 次；质量检查拒绝 {{ generation.outcome_summary.quality_rejected_count }} 道。</small>
    <small v-if="generation.outcome_summary.not_executed_count ?? generation.outcome_summary.not_attempted_count">另有 {{ generation.outcome_summary.not_executed_count ?? generation.outcome_summary.not_attempted_count }} 道尚未执行，不算质量检查失败。</small>
    <small v-if="generation.outcome_summary.unresolved_count">{{ generation.outcome_summary.unresolved_count }} 道缺少完整执行记录，请读取批次状态。</small>
    <small>本批次模型请求 {{ generation.outcome_summary.provider_calls }} 次；读取结果不会再次调用模型。</small>
  </div>
</template>
<style scoped>
.generation-outcome{margin:8px 0;font-size:12px;line-height:1.65;overflow-wrap:anywhere}.generation-outcome p{margin:0;font-weight:500}.generation-outcome small{display:block;color:var(--text-secondary)}
</style>
