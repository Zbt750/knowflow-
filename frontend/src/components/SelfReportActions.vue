<script setup lang="ts">
import type { SelfGrade } from "../types/practice";
defineProps<{ disabled: boolean; testPrefix?: string }>();
const emit = defineEmits<{ grade: [grade: SelfGrade] }>();
const choices: Array<{ value: SelfGrade; label: string }> = [
  { value: "mastered", label: "独立完成" },
  { value: "partial", label: "部分完成" },
  { value: "not_mastered", label: "未完成" },
];
</script>
<template>
  <details class="self-report" data-testid="self-report">
    <summary>自行对照记录</summary>
    <p>记录本题表现，不作为机器判题或毕业确认。</p>
    <div class="actions">
      <button v-for="choice in choices" :key="choice.value" type="button" :disabled="disabled"
        :data-testid="testPrefix ? `${testPrefix}-${choice.value.replace('_', '-')}` : undefined"
        @click="emit('grade', choice.value)">{{ choice.label }}</button>
    </div>
  </details>
</template>
<style scoped>
.self-report { margin-top: 10px; font-size: 13px; color: var(--text-secondary); }
summary { cursor: pointer; width: fit-content; }
p { color: var(--text-tertiary); font-size: 12px; margin: 8px 0; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
button { border-radius: 8px; padding: 6px 10px; }
</style>
