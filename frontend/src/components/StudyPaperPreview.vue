<script setup lang="ts">
import type { PlanItemView } from "../types/practice";

defineProps<{ items: PlanItemView[]; testId?: string }>();
</script>

<template>
  <ol class="paper-list" :data-testid="testId ?? 'paper-list'">
    <li v-for="(item, index) in items" :id="`paper-item-${item.id}`" :key="item.id" class="paper-item">
      <slot name="item" :item="item" :index="index" />
    </li>
  </ol>
</template>

<style scoped>
.paper-list { margin: 0; padding: 0; list-style: none; }
.paper-item { min-width: 0; }
</style>
