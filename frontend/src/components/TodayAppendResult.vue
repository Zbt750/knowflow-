<script setup lang="ts">
import type {TodayAppendResult} from '../api/todayAppend';
import {typeLabel} from '../lib/labels';
import MarkdownContent from './MarkdownContent.vue';
import {questionSourceLabel} from '../lib/questionSourceLabel';
defineProps<{result:TodayAppendResult}>();
const difficulties:Record<string,string>={basic:'基础',medium:'中等',hard:'较难',challenge:'综合挑战'};
</script>
<template>
 <section v-if="result.status==='committed'" data-testid="today-append-result" :data-operation-id="result.operation_id">
  <p>已加入今日卷 · 本次新增 {{result.added_count}} 道 · 该卷当前共 {{result.total_count}} 道</p>
  <p class="position-note">{{result.study_date}} 卷 · 以下为当前题号，按该卷当前排序显示。</p>
  <article v-for="item in result.items" :key="item.item_id" data-testid="today-added-question" :data-item-id="item.item_id" :data-version-id="item.question_version_id">
   <h4>已加入今日卷 · 第 {{item.number}} 题</h4>
   <MarkdownContent :text="item.stem"/>
   <ul v-if="item.options"><li v-for="(text,key) in item.options" :key="key"><span>{{key}}.</span><MarkdownContent :text="text"/></li></ul>
   <p>{{item.kp_name}} · {{typeLabel(item.question_type)}}<template v-if="item.difficulty"> · {{difficulties[item.difficulty]??item.difficulty}}</template></p>
   <p>来源：{{questionSourceLabel(item.source_category)}}<template v-if="item.question_source.paper_title"> · {{item.question_source.paper_title}}</template></p>
   <p>{{item.estimated_minutes===null?'暂无预计用时':`预计 ${item.estimated_minutes} 分钟`}}</p>
  </article>
  <RouterLink to="/study">前往今日学习做题</RouterLink>
 </section>
</template>
<style scoped>
section { margin-top:12px; min-width:0; }
article { padding:12px 0; border-top:1px solid var(--border); }
h4 { margin:0 0 10px; }
ul { padding-left:1.4em; }
li { display:flex; gap:8px; }
.position-note { color:var(--text-secondary); font-size:.85rem; }
</style>
