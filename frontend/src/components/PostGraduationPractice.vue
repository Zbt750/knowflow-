<script setup lang="ts">
import type {components} from '../api/types';
import {postPracticeSummary} from '../lib/postPractice';
defineProps<{practice:components['schemas']['PostGraduationPractice'];nodeId:string}>();
</script>
<template>
  <section v-if="practice.applicable" class="post-practice" data-testid="post-graduation-practice" aria-label="毕业后近期练习表现">
    <p class="foundation">{{postPracticeSummary(practice)?.foundation}}</p>
    <h3>近期表现：{{practice.label}}</h3>
    <p>{{practice.reason}}</p><p class="muted">{{practice.evidence_summary}}</p>
    <p class="muted">最近可靠练习：{{practice.last_reliable_practice_at?new Date(practice.last_reliable_practice_at).toLocaleString():'暂无毕业后可靠记录'}}</p>
    <RouterLink :to="{path:'/study',query:{review_node_id:nodeId}}">让奶蛙提出复习方案 ↗</RouterLink>
    <details><summary>评价边界</summary><p v-for="item in practice.limitations" :key="item">{{item}}</p><p>近期练习表现不替代严格毕业评价，生成新题本身不代表进步。</p></details>
  </section>
</template>
<style scoped>
.post-practice{border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin:14px 0;font-size:13px;background:white}h3{font-size:15px;margin:6px 0}.foundation,.muted{color:var(--text-secondary)}p{line-height:1.65;margin:6px 0}details{margin-top:10px;color:var(--text-secondary)}
</style>
