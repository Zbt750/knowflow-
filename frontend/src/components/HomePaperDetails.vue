<script setup lang="ts">
import type {HomePaper,HomePreview} from '../api/homeRecommendation';
import HomeFormulaContent from './HomeFormulaContent.vue';
import {homePreviewIdentity} from '../lib/homePreviewIdentity';
import {questionSourceLabel} from '../lib/questionSourceLabel';
defineProps<{preview:HomePreview;paper:HomePaper}>();
const difficultyName=(value:string)=>({basic:'基础',medium:'中等',hard:'较难',improved:'中等',comprehensive:'综合'} as Record<string,string>)[value]??value;
const addedQuestions=(paper:HomePaper)=>paper.questions.filter(q=>paper.diff?.added.includes(q.question_id));
</script>
<template>
 <section class="paper-detail" data-testid="home-paper-detail" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :data-preview-key="homePreviewIdentity(preview)" aria-label="完整试卷预览">
  <p data-testid="home-detail-summary">{{paper.questions.length}} 道 · {{paper.total_minutes}} 分钟 · 预算 {{preview.budget_minutes}} 分钟</p>
  <small>方案 {{preview.task_id}}</small>
  <details v-if="paper.diff"><summary>相较原推荐：增加 {{paper.diff.added.length}} 道，移除 {{paper.diff.removed.length}} 道，保留 {{paper.diff.retained.length}} 道</summary><ul><li v-for="q in preview.context.baseline?.questions??[]" :key="q.question_id">{{paper.diff.removed.includes(q.question_id)?'移除':'保留'}} · {{q.kp_name}} · {{q.minutes}} 分钟<HomeFormulaContent :text="q.stem"/></li><li v-for="q in addedQuestions(paper)" :key="q.question_id">增加 · {{q.kp_name}} · {{q.minutes}} 分钟<HomeFormulaContent :text="q.stem"/></li></ul></details>
  <ol><li v-for="q in paper.questions" :key="q.question_id"><h4>{{q.kp_name}} · {{q.minutes}} 分钟<span v-if="q.difficulty"> · 难度：{{difficultyName(q.difficulty)}}</span></h4><HomeFormulaContent :text="q.stem"/><p v-if="preview.context.bank_selection?.matches?.[q.question_id]" data-testid="home-bank-match">来源：{{questionSourceLabel(preview.context.bank_selection.matches[q.question_id].source_category??'unclassified_public')}}<span v-if="preview.context.bank_selection.matches[q.question_id].match_basis">；同知识点、同题型<span v-if="preview.context.bank_selection.matches[q.question_id].match_basis?.shared_skill_tags?.length">；共有技能标签：{{preview.context.bank_selection.matches[q.question_id].match_basis?.shared_skill_tags?.join('、')}}</span><span v-if="preview.context.bank_selection.matches[q.question_id].match_basis?.same_variant_group">；同一变式组</span></span>。仅显示可核实依据。</p><div v-for="(value,key) in q.options" :key="key">{{key}}. <HomeFormulaContent :text="value"/></div><div>选题理由：<HomeFormulaContent :text="q.reason"/></div><small>题目 {{q.question_id}} · 版本 {{q.question_version_id}}</small></li></ol>
 </section>
</template>
<style scoped>
.paper-detail{min-width:0;max-width:100%;width:100%;box-sizing:border-box}.paper-detail ol{padding-left:24px}.paper-detail li{min-width:0;margin-block:16px;overflow-wrap:anywhere}.paper-detail h4{margin-block:10px}.paper-detail small{overflow-wrap:anywhere}.paper-detail :deep(.markdown-content){max-width:100%;min-width:0}.paper-detail :deep(.katex-display){overflow-x:auto;overflow-y:hidden;max-width:100%}
</style>
