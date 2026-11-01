<script setup lang="ts">
import {computed} from 'vue';
import MarkdownContent from './MarkdownContent.vue';
import {answerExplanation} from '../lib/answerExplanation';
const props=defineProps<{text:string}>();
const view=computed(()=>answerExplanation(props.text));
</script>
<template>
  <section class="answer-explanation">
    <MarkdownContent v-if="view.text" :text="view.text" />
    <section v-if="view.facts.length" class="calculation-facts" aria-label="计算记录">
      <h3>计算要点</h3>
      <dl><template v-for="(fact,index) in view.facts" :key="index"><dt>{{fact.label}}</dt><dd>{{fact.value}}</dd></template></dl>
      <details><summary>查看原始计算记录（技术信息）</summary><pre>{{view.raw}}</pre></details>
      <p class="calculation-note">以上为题目附带的计算记录，不代表独立数学核验。</p>
    </section>
  </section>
</template>
<style scoped>
.answer-explanation{min-width:0}.calculation-facts{margin-top:1rem}h3{font-size:1rem;margin:.5rem 0}dl{margin:0}dt{font-weight:600;margin-top:.5rem}dd{margin:.2rem 0;white-space:pre-wrap;overflow-wrap:anywhere}details{margin-top:1rem;font-size:.85rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}.calculation-note{font-size:.8rem;color:var(--text-secondary)}
</style>
