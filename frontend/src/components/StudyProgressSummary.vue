<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ completed: number; total: number; label: string; accessibleLabel: string; testId?: string }>();
const percent = computed(() => props.total > 0 ? Math.min(100, Math.round(props.completed / props.total * 100)) : 0);
</script>

<template>
  <section class="paper-aside-heading" :data-testid="testId ?? 'study-progress-summary'">
    <span>{{ label }} <strong>{{ completed }} / {{ total }}</strong></span>
    <div class="paper-aside-progress" role="progressbar" :aria-valuenow="completed" :aria-valuemin="0" :aria-valuemax="total" :aria-label="accessibleLabel">
      <i :style="{ width: `${percent}%` }" />
    </div>
  </section>
</template>

<style scoped>
.paper-aside-heading { display:grid; gap:9px; }
.paper-aside-heading span { color:var(--text-secondary, #596358); font-size:12px; }
.paper-aside-progress { height:6px; overflow:hidden; border-radius:8px; background:var(--surface-subtle, #e9eee4); }
.paper-aside-progress i { display:block; height:100%; border-radius:inherit; background:var(--accent, #4c6d58); transition:width .2s ease; }
</style>
