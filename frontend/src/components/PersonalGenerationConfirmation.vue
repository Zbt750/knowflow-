<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { GenerationConfirmation } from "../api/personalQuestions";
import MarkdownContent from './MarkdownContent.vue';
const props = defineProps<{ confirmation: GenerationConfirmation; busy: boolean }>();
const emit = defineEmits<{ confirm: [kpId: string]; confirmTargets: [targets: NonNullable<GenerationConfirmation['proposed_targets']>]; cancel: []; selectionChange: [kpId: string | null] }>();
const selected = ref("");
const node = computed(() => props.confirmation.nodes.find(item => item.kp_id === selected.value));
const typeLabel=(type:string)=>({single_choice:'选择题',fill_blank:'填空题',calculation:'计算题',proof:'证明题',subjective:'主观题'} as Record<string,string>)[type]??type;
const difficultyLabel=(level:string)=>({basic:'基础',improved:'中等',comprehensive:'综合挑战'} as Record<string,string>)[level]??level;
watch(() => props.confirmation, value => { selected.value = value.selected_kp_id ?? ""; }, { immediate: true });
watch(selected, value => emit("selectionChange", value || null));
</script>
<template>
  <section class="generation-confirmation" data-testid="generation-confirmation">
    <strong>先确认出题知识点</strong>
    <p>{{ confirmation.message }}</p>
    <details v-if="confirmation.reference_text"><summary>本次变式的原题</summary><MarkdownContent :text="confirmation.reference_text" /></details>
    <template v-if="confirmation.nodes.length">
      <template v-if="confirmation.proposed_targets?.length">
        <div class="generation-allocation" data-testid="generation-allocation">
          <strong>本次分配（{{ confirmation.question_count }} 道）</strong>
          <ul>
            <li v-for="(target,index) in confirmation.proposed_targets" :key="`${target.kp_id}-${target.question_type}-${target.difficulty}-${index}`">
              {{ target.name }}：{{ target.count }} 道{{ typeLabel(target.question_type) }} · {{ difficultyLabel(target.difficulty) }}
            </li>
          </ul>
        </div>
        <small>确认后只生成个人练习题，不会自动加入正式今日卷。也可以在聊天框回复“确定”接受这份分配。</small>
      </template>
      <template v-else>
        <label>本次知识点
          <select v-model="selected" :disabled="busy" data-testid="generation-node-select">
            <option value="" disabled>请选择一个具体知识点</option>
            <option v-for="item in confirmation.nodes" :key="item.kp_id" :value="item.kp_id">{{ item.name }}</option>
          </select>
        </label>
        <small>计划生成 {{ confirmation.question_count }} 道题。选择具体知识点后，点按钮或在聊天框回复“确定”都可以继续。AI参考练习不计入正式毕业证据，生成后由你决定是否加入今日学习。</small>
      </template>
      <small v-if="confirmation.difficulty_steps?.length">各题目标难度：{{ confirmation.difficulty_steps.join(' → ') }}。实际难度仍需核验。</small>
      <div class="generation-confirmation-actions">
        <button v-if="confirmation.proposed_targets?.length" type="button" :disabled="busy" data-testid="confirm-generation-plan" @click="emit('confirmTargets', confirmation.proposed_targets)">{{ busy ? '正在处理…' : '确认分配并生成' }}</button>
        <button v-else type="button" :disabled="busy || !node" data-testid="confirm-generation-node" @click="node && emit('confirm', node.kp_id)">{{ busy ? '正在处理…' : '确认知识点并生成' }}</button>
        <button type="button" :disabled="busy" @click="emit('cancel')">暂不生成</button>
      </div>
    </template>
  </section>
</template>
<style scoped>
.generation-confirmation{display:grid;gap:10px;margin:12px 0;padding:15px;border:1px solid var(--border);border-radius:14px;background:#f4f6ee}
.generation-confirmation p{margin:0;font-size:13px;line-height:1.7}
.generation-allocation{display:grid;gap:4px;padding:10px 12px;border-radius:10px;background:#fff}
.generation-allocation ul{margin:0;padding-left:20px}
.generation-allocation li{font-size:13px;line-height:1.6}
.generation-confirmation label{display:grid;gap:6px;font-size:12px}
.generation-confirmation select{width:100%;min-height:40px;padding:7px 10px;background:#fff;border:1px solid var(--border);border-radius:12px}
.generation-confirmation small{color:var(--text-secondary);line-height:1.6}
.generation-confirmation-actions{display:flex;flex-wrap:wrap;gap:8px}
</style>
