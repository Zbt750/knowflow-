<script setup lang="ts">
import type { KnowledgeNodeView } from "../types/practice";

const props = defineProps<{
  nodes: KnowledgeNodeView[];
  selectedIds: readonly string[];
  selectedCounts: ReadonlyMap<string, number>;
  expandedIds: ReadonlySet<string>;
  collapsedIds: ReadonlySet<string>;
  autoExpand: boolean;
  level: number;
}>();

const emit = defineEmits<{
  "toggle-branch": [node: KnowledgeNodeView];
  "toggle-selection": [id: string];
}>();

function children(node: KnowledgeNodeView): KnowledgeNodeView[] {
  return Array.isArray(node.children) ? node.children : [];
}

function isExpanded(node: KnowledgeNodeView): boolean {
  return !props.collapsedIds.has(node.id) && (props.expandedIds.has(node.id) || props.autoExpand);
}
</script>

<template>
  <ul class="scope-tree" :aria-label="level === 1 ? '练习范围知识树' : undefined">
    <li v-for="node in nodes" :key="node.id" class="scope-tree__item">
      <template v-if="children(node).length">
        <button
          type="button"
          class="scope-tree__branch"
          :class="{ 'scope-tree__branch--selected': (selectedCounts.get(node.id) ?? 0) > 0 }"
          :aria-label="node.name + ((selectedCounts.get(node.id) ?? 0) > 0 ? '，已选 ' + selectedCounts.get(node.id) + ' 个知识点' : '')"
          :aria-expanded="isExpanded(node)"
          :aria-controls="`scope-children-${node.id}`"
          :data-testid="`scope-branch-${node.code}`"
          @click="emit('toggle-branch', node)"
        >
          <svg class="scope-tree__chevron" :class="{ 'scope-tree__chevron--open': isExpanded(node) }" viewBox="0 0 16 16" aria-hidden="true"><path d="m6 4 4 4-4 4" /></svg>
          <span>{{ node.name }}</span>
          <small v-if="(selectedCounts.get(node.id) ?? 0) > 0" class="scope-tree__selected-count">已选 {{ selectedCounts.get(node.id) }}</small>
        </button>
        <div v-if="isExpanded(node)" :id="`scope-children-${node.id}`" class="scope-tree__children">
          <KnowledgeScopeTree
            :nodes="children(node)"
            :selected-ids="selectedIds"
            :selected-counts="selectedCounts"
            :expanded-ids="expandedIds"
            :collapsed-ids="collapsedIds"
            :auto-expand="autoExpand"
            :level="level + 1"
            @toggle-branch="emit('toggle-branch', $event)"
            @toggle-selection="emit('toggle-selection', $event)"
          />
        </div>
      </template>
      <div v-else-if="node.is_assessable" class="study-range-row" :class="{ 'study-range-row--selected': selectedIds.includes(node.id) }">
        <span class="scope-tree__leaf-marker" aria-hidden="true"></span>
        <span class="scope-tree__name">{{ node.name }}</span>
        <button
          type="button"
          class="study-range-row__toggle"
          :id="`scope-leaf-${node.id}`"
          :aria-pressed="selectedIds.includes(node.id)"
          :aria-label="(selectedIds.includes(node.id) ? '移出' : '加入') + node.name"
          :data-testid="`pick-node-${node.code}`"
          @click="emit('toggle-selection', node.id)"
        >{{ selectedIds.includes(node.id) ? "移出" : "加入" }}</button>
      </div>
      <span v-else class="scope-tree__empty">{{ node.name }} · 暂无知识点</span>
    </li>
  </ul>
</template>

<style scoped>
.scope-tree { margin: 0; padding: 0; list-style: none; }
.scope-tree__item { min-width: 0; margin: 0; padding: 0; list-style: none; }
.scope-tree__branch { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 40px; padding: 6px 8px; border: 0; border-radius: 7px; color: var(--text); background: transparent; text-align: left; font-size: 13px; font-weight: 560; }
.scope-tree__branch:hover { background: #f4f7fb; }
.scope-tree__branch--selected { color: #345d87; background: #edf5ff; }
.scope-tree__selected-count { flex: 0 0 auto; margin-left: auto; color: #527aa1; font-size: 11px; font-weight: 400; }
.scope-tree__branch > span { min-width: 0; overflow-wrap: anywhere; }
.scope-tree__chevron { flex: 0 0 14px; width: 14px; height: 14px; fill: none; stroke: #86919e; stroke-width: 1.5; transition: transform .12s ease; }
.scope-tree__chevron--open { transform: rotate(90deg); }
.scope-tree__children { margin: 0 0 4px 14px; padding-left: 12px; border-left: 1px solid #e5eaf0; }
.study-range-row { display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 5px 7px; border-radius: 7px; }
.study-range-row--selected { background: #f7faff; }
.scope-tree__leaf-marker { flex: 0 0 4px; width: 4px; height: 4px; margin: 0 5px; border-radius: 50%; background: #b8c2ce; }
.scope-tree__name { flex: 1; min-width: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.study-range-row__toggle { flex: 0 0 auto; min-width: 44px; min-height: 30px; padding: 4px 8px; border: 0; border-radius: 6px; color: #345d87; background: transparent; font-size: 12px; }
.study-range-row__toggle[aria-pressed="true"] { color: var(--text-tertiary); }
.study-range-row__toggle:hover { color: var(--text); background: #eaf0f7; }
.scope-tree__empty { display: block; padding: 10px 8px; color: var(--text-tertiary); font-size: 12px; }
@media (max-width: 600px) {
  .scope-tree__children { margin-left: 8px; padding-left: 7px; }
  .scope-tree__branch, .study-range-row { min-height: 44px; }
  .study-range-row__toggle { min-height: 36px; }
}
@media (prefers-reduced-motion: reduce) { .scope-tree__chevron { transition: none; } }
</style>
