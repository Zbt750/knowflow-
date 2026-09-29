<script setup lang="ts">
import type { KnowledgeNodeView } from "../types/practice";

interface PickerQuestion {
  id: string;
  stem: string;
  is_variant: boolean;
}

const props = defineProps<{
  nodes: KnowledgeNodeView[];
  expandedIds: ReadonlySet<string>;
  collapsedIds: ReadonlySet<string>;
  questions: Record<string, PickerQuestion[] | undefined>;
  questionLoadingIds: ReadonlySet<string>;
  selectedQuestionIds: readonly string[];
  autoExpandBranches: boolean;
  level: number;
}>();

const emit = defineEmits<{
  "toggle-node": [node: KnowledgeNodeView];
  "toggle-question": [questionId: string];
}>();

function hasChildren(node: KnowledgeNodeView): boolean {
  return Array.isArray(node.children) && node.children.length > 0;
}

function nodeChildren(node: KnowledgeNodeView): KnowledgeNodeView[] {
  return Array.isArray(node.children) ? node.children : [];
}

function canExpand(node: KnowledgeNodeView): boolean {
  return hasChildren(node) || node.is_assessable;
}

function isExpanded(node: KnowledgeNodeView): boolean {
  if (props.collapsedIds.has(node.id)) return false;
  if (props.expandedIds.has(node.id)) return true;
  return hasChildren(node) && props.autoExpandBranches;
}
</script>

<template>
  <ul
    class="question-picker-tree"
    :role="level === 1 ? 'tree' : 'group'"
    :aria-label="level === 1 ? '知识点树' : undefined"
    :data-testid="level === 1 ? 'question-picker-tree' : undefined"
  >
    <li
      v-for="node in nodes"
      :key="node.id"
      class="question-picker-tree__item"
      role="treeitem"
      :aria-level="level"
      :aria-expanded="canExpand(node) ? isExpanded(node) : undefined"
      :data-testid="`question-picker-tree-node-${node.code}`"
    >
      <div class="question-picker-tree__row" :class="{ 'question-picker-tree__row--branch': hasChildren(node) }">
        <button
          type="button"
          class="question-picker-tree__toggle"
          :class="{ 'question-picker-tree__toggle--branch': hasChildren(node) }"
          :aria-expanded="canExpand(node) ? isExpanded(node) : undefined"
          :data-testid="`question-picker-node-${node.code}`"
          @click="emit('toggle-node', node)"
        >
          <span class="question-picker-tree__marker" aria-hidden="true">
            {{ hasChildren(node) ? (isExpanded(node) ? '▾' : '▸') : node.is_assessable ? (isExpanded(node) ? '▾' : '▸') : '·' }}
          </span>
          <span class="question-picker-tree__name">{{ node.name }}</span>
          <span v-if="node.is_assessable" class="question-picker-tree__kind">知识点</span>
        </button>
      </div>

      <KnowledgeQuestionPickerTree
        v-if="hasChildren(node) && isExpanded(node)"
        :nodes="nodeChildren(node)"
        :expanded-ids="expandedIds"
        :collapsed-ids="collapsedIds"
        :questions="questions"
        :question-loading-ids="questionLoadingIds"
        :selected-question-ids="selectedQuestionIds"
        :auto-expand-branches="autoExpandBranches"
        :level="level + 1"
        @toggle-node="emit('toggle-node', $event)"
        @toggle-question="emit('toggle-question', $event)"
      />

      <div
        v-else-if="node.is_assessable && isExpanded(node)"
        class="question-picker-tree__question-group"
        role="group"
        :aria-label="`${node.name}的题库`"
      >
        <p v-if="questionLoadingIds.has(node.id)" class="question-picker-tree__state" role="status">
          正在读取题库…
        </p>
        <ul v-else-if="questions[node.id]?.length" class="question-picker-tree__questions">
          <li v-for="question in questions[node.id]" :key="question.id">
            <label class="question-picker-tree__question">
              <input
                type="checkbox"
                :checked="selectedQuestionIds.includes(question.id)"
                @change="emit('toggle-question', question.id)"
              />
              <span>{{ question.stem }}</span>
              <span v-if="question.is_variant" class="tag">变式题</span>
            </label>
          </li>
        </ul>
        <p v-else-if="questions[node.id]" class="question-picker-tree__state">
          该知识点暂无可追加练习题。
        </p>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.question-picker-tree {
  margin: 4px 0;
  padding: 0;
  list-style: none;
}

.question-picker-tree__item {
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.question-picker-tree[role="group"] {
  margin: 1px 0 5px 12px;
  padding-left: 12px;
  border-left: 1px solid #e1e5eb;
}

.question-picker-tree__row {
  min-width: 0;
  border-bottom: 1px solid #edf0f4;
}

.question-picker-tree__toggle {
  display: flex;
  width: 100%;
  min-height: 35px;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  text-align: left;
}

.question-picker-tree__toggle:hover:not(:disabled) {
  background: #f4f7fb;
  color: var(--text);
}

.question-picker-tree__toggle--branch {
  color: var(--text);
  font-weight: 570;
}

.question-picker-tree__marker {
  display: inline-grid;
  width: 15px;
  flex: 0 0 15px;
  place-items: center;
  color: #77808c;
  font-size: 12px;
}

.question-picker-tree__name {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}

.question-picker-tree__kind {
  flex: none;
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 400;
}

.question-picker-tree__question-group {
  margin: 3px 0 9px 20px;
  padding-left: 12px;
  border-left: 1px solid #e1e5eb;
}

.question-picker-tree__questions {
  margin: 0;
  padding: 0;
  list-style: none;
}

.question-picker-tree__questions li {
  padding: 5px 3px;
}

.question-picker-tree__question {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
  cursor: pointer;
}

.question-picker-tree__question input {
  flex: none;
  margin-top: 3px;
}

.question-picker-tree__state {
  margin: 5px 0;
  color: var(--text-tertiary);
  font-size: 12px;
}

@media (max-width: 600px) {
  .question-picker-tree__question-group {
    margin-left: 12px;
    padding-left: 8px;
  }
}
</style>
