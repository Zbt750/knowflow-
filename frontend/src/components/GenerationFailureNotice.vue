<script setup lang="ts">
import type { GenerationResult } from '../api/personalQuestions';
import GenerationOutcomeSummary from './GenerationOutcomeSummary.vue';
defineProps<{ generation: GenerationResult }>();
const stages:Record<string,string> = {provider_response:'模型输出',response_parse:'响应解析',content_check:'题目内容',
  answer_check:'答案校验',difficulty_check:'难度要求检查',save_check:'保存前检查',save_question:'题目保存',provider_request:'模型请求',
  budget_check:'预算检查',quality_check:'质量检查',generation_processing:'出题处理'};
</script>
<template>
  <section v-if="generation.diagnostics?.length" class="generation-diagnostics" data-testid="generation-diagnostics" aria-label="出题诊断">
    <GenerationOutcomeSummary v-if="!generation.question_ids.length" :generation="generation" />
    <div v-for="(item,index) in generation.diagnostics" :key="index">
      <p>{{ item.message }}</p>
      <small>{{ stages[item.stage] || '出题检查' }} · <code>{{ item.code }}</code></small>
    </div>
    <small>未自动重试或加入今日卷。重新提出出题请求会产生新的模型调用；同一批次的状态读取不会再次调用模型。</small>
  </section>
</template>
<style scoped>
.generation-diagnostics{margin:8px 0 14px;padding:12px 16px;border-left:3px solid #b69a63;border-radius:10px;background:#faf7ef;color:#5c5444;font-size:13px;line-height:1.7}
.generation-diagnostics p{margin:0 0 4px}.generation-diagnostics small{display:block;overflow-wrap:anywhere}.generation-diagnostics code{font-size:11px}
</style>
