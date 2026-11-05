<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { PlanItemView } from "../types/practice";

const props = defineProps<{ items: PlanItemView[]; testId?: string }>();
const emit = defineEmits<{ (event: "item-viewed", itemId: string): void }>();
const list = ref<HTMLOListElement | null>(null);
const viewed = new Set<string>();
let observer: IntersectionObserver | null = null;

function observeVisibleItems(): void {
  observer?.disconnect();
  observer = null;
  if (!list.value || typeof IntersectionObserver === "undefined") return;
  const itemById = new Map(props.items.map((item) => [item.id, item]));
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || entry.intersectionRatio < 0.15) continue;
      const id = (entry.target as HTMLElement).dataset.itemId;
      if (!id || !itemById.has(id) || viewed.has(id)) continue;
      viewed.add(id);
      observer?.unobserve(entry.target);
      emit("item-viewed", id);
    }
  }, { threshold: [0.15] });
  for (const element of list.value.querySelectorAll<HTMLElement>("[data-item-id]")) {
    const id = element.dataset.itemId;
    if (id && !viewed.has(id)) observer.observe(element);
  }
}

onMounted(() => { void nextTick(observeVisibleItems); });
watch(() => props.items.map((item) => item.id).join("\u0000"), () => { void nextTick(observeVisibleItems); });
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <ol ref="list" class="paper-list" :data-testid="testId ?? 'paper-list'">
    <li v-for="(item, index) in items" :id="`paper-item-${item.id}`" :key="item.id" :data-item-id="item.id" class="paper-item">
      <slot name="item" :item="item" :index="index" />
    </li>
  </ol>
</template>

<style scoped>
.paper-list { margin: 0; padding: 0; list-style: none; }
.paper-item { min-width: 0; }
</style>
