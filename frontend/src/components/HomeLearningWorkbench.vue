<script setup lang="ts">
import {ref} from 'vue';
import HomeRecommendationAssistant from './HomeRecommendationAssistant.vue';
const props=defineProps<{extension:boolean;selectedKpIds:string[];budget:string;formalPaper?:{plan_id:string;total_count:number;estimated_minutes:number}|null}>();
const emit=defineEmits<{confirmed:[];practice:[];scopeChange:[ids:string[]]}>();
const assistant=ref<InstanceType<typeof HomeRecommendationAssistant>|null>(null);
defineExpose({prepare:(action='default')=>assistant.value?.prepare(action)});
</script>
<template>
 <slot v-if="props.extension"/>
 <section v-else class="learning-workbench" data-testid="home-learning-workbench" aria-label="今日学习工作台">
  <HomeRecommendationAssistant ref="assistant" workbench :formal-paper="formalPaper" :read-only="!!formalPaper" :selected-kp-ids="selectedKpIds" :budget="budget" @confirmed="emit('confirmed')" @practice="emit('practice')" @scope-change="emit('scopeChange',$event)"><template #manual-controls><slot name="scope-editor"/></template></HomeRecommendationAssistant>
 </section>
</template>
<style scoped>
.learning-workbench{min-width:0}.workbench-steps{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 18px;color:var(--text-secondary,#62745b);font-size:12px}.workbench-steps span{padding:8px 12px;background:var(--surface,#fffefb);border:1px solid var(--border,#d7dfd0);border-radius:999px}
</style>
