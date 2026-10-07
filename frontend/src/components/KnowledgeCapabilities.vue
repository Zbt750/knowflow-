<script setup lang="ts">
import type { components } from "../api/types";
defineProps<{ profile: components["schemas"]["CapabilityProfile"] }>();
</script>

<template>
  <section class="capabilities" aria-label="学习证据" data-testid="knowledge-capabilities">
    <h3>学习证据</h3>
    <details v-for="dimension in profile.dimensions" :key="dimension.key" :data-testid="`capability-${dimension.key}`">
      <summary>
        <span>{{ dimension.label }}</span>
        <span class="capability-status" :data-status="dimension.status">{{ dimension.status_label }}</span>
      </summary>
      <p>{{ dimension.reason }}</p>
      <p class="capability-counts">在线题 {{ dimension.online_question_count }} · 可可靠核对 {{ dimension.reliable_grading_question_count }} · 独立证据 {{ dimension.independent_question_count }}</p>
      <p v-if="dimension.observed_skill_tags?.length" class="capability-counts">已有证据的考法：{{ (dimension.observed_skill_tags ?? []).join('、') }}</p>
    </details>
    <p class="capability-note">{{ profile.note }}</p>
    <p v-if="profile.history_truncated" class="capability-note">近期作答统计仅含最近 100 次；独立证据以当前有效窗口为准。</p>
    <p v-if="profile.confirmation_lookup_truncated" class="capability-note">部分历史尚未完整核对，未计为独立证据。</p>
  </section>
</template>

<style scoped>
.capabilities { margin: 22px 0; }
h3 { font-size: 13px; font-weight: 600; margin: 0 0 8px; color: var(--text-secondary); }
details { margin: 0; }
summary { cursor: pointer; display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; font-size: 13px; list-style: none; }
summary::after { content: '⌄'; color: var(--text-tertiary); }
details[open] > summary::after { content: '⌃'; }
summary > span:first-child { flex: 1; }
.capability-status { color: var(--text-tertiary); white-space: nowrap; }
.capability-status[data-status="independent_evidence"] { color: #47715e; }
.capability-status[data-status="needs_retest"] { color: #916341; }
details p { font-size: 12px; line-height: 1.6; margin: 2px 0 8px; color: var(--text-secondary); overflow-wrap: anywhere; }
.capability-counts, .capability-note { font-size: 11px; color: var(--text-tertiary); }
.capability-note { margin: 10px 0 0; line-height: 1.6; }
</style>
