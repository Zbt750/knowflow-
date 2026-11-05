<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  name: "study" | "knowledge" | "materials" | "chat" | "plus" | "book" | "settings" | "sidebar-collapse" | "sidebar-expand";
  size?: number;
}>(), {
  size: 18,
});

const paths: Record<typeof props.name, string[]> = {
  study: [
    "M5 5.5h14v14H5z",
    "M8 3v5M16 3v5M5 9.5h14",
    "m8.5 14 2 2 4-4",
  ],
  knowledge: [
    "M12 4v4M12 8H6v4M12 8h6v4M12 8v8",
    "M4 12h4v4H4zM10 16h4v4h-4zM16 12h4v4h-4z",
  ],
  materials: [
    "M3.5 6.5h6l2-2h9v15h-17z",
    "M7 11h10M7 15h7",
  ],
  chat: [
    "M4 5.5h16v11H9l-5 3z",
    "M8 10h8M8 13h5",
  ],
  plus: ["M12 5v14M5 12h14"],
  settings: [
    "M12 8.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 0 0 0-7z",
    "M10.4 2.8h3.2l.5 2a7.4 7.4 0 0 1 1.5.6l1.8-1.1 2.3 2.3-1.1 1.8c.3.5.5 1 .6 1.5l2 .5v3.2l-2 .5a7.4 7.4 0 0 1-.6 1.5l1.1 1.8-2.3 2.3-1.8-1.1a7.4 7.4 0 0 1-1.5.6l-.5 2h-3.2l-.5-2a7.4 7.4 0 0 1-1.5-.6l-1.8 1.1-2.3-2.3 1.1-1.8a7.4 7.4 0 0 1-.6-1.5l-2-.5v-3.2l2-.5c.1-.5.3-1 .6-1.5L4.3 6.6l2.3-2.3 1.8 1.1a7.4 7.4 0 0 1 1.5-.6z",
  ],
  book: [
    "M4 5.5c3-1 5-.5 8 1.5v13c-3-2-5-2.5-8-1.5z",
    "M20 5.5c-3-1-5-.5-8 1.5v13c3-2 5-2.5 8-1.5z",
  ],
  "sidebar-collapse": ["M4 4.5h16v15H4z", "M9 4.5v15", "m15 9-2.5 3 2.5 3"],
  "sidebar-expand": ["M4 4.5h16v15H4z", "M9 4.5v15", "m12 9 2.5 3-2.5 3"],
};

const iconPaths = computed(() => paths[props.name]);
</script>

<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="path in iconPaths" :key="path" :d="path" />
  </svg>
</template>
