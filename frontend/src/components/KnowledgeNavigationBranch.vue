<script setup lang="ts">
import type {KnowledgeNodeView} from '../types/practice';
import {stateLabel} from '../lib/labels';
defineProps<{node:KnowledgeNodeView;depth:number;selectedId:string|null;isOpen:(node:KnowledgeNodeView)=>boolean}>();
const emit=defineEmits<{select:[node:KnowledgeNodeView];toggle:[node:KnowledgeNodeView]}>();
</script>
<template>
  <li role="treeitem" :aria-expanded="node.children.length ? isOpen(node) : undefined"
      :aria-selected="selectedId===node.id" :data-node-id="node.id" :data-node-code="node.code"
      class="knowledge-nav-item" :class="{'is-selected':selectedId===node.id,'is-branch':node.children.length}">
    <div class="knowledge-nav-row">
      <button v-if="node.children.length" type="button" class="knowledge-nav-toggle" :aria-label="`${isOpen(node)?'收起':'展开'}${node.name}`"
        :aria-expanded="isOpen(node)" @click="emit('toggle',node)"><span aria-hidden="true">{{isOpen(node)?'⌄':'›'}}</span></button>
      <span v-else class="knowledge-nav-marker" aria-hidden="true">·</span>
      <button type="button" class="knowledge-nav-title" :data-testid="`knowledge-node-${node.code}`"
        @click="node.children.length ? emit('toggle',node) : emit('select',node)">
        <span>{{node.name}}</span>
        <small>{{node.children.length ? (depth===0?'章节':'模块') : node.is_reference_only?'题源索引 · 非考核':node.is_assessable?'知识点':'导航节点'}}<template v-if="!node.children.length"> · {{node.post_graduation?.applicable?'已毕业':stateLabel(node.state)}}<template v-if="node.practice_eligible_question_count!=null"> · {{node.practice_eligible_question_count}}题</template></template></small>
      </button>
      <button v-if="node.children.length" type="button" class="knowledge-nav-view" :aria-label="`查看${node.name}概览`" @click="emit('select',node)">概览</button>
    </div>
    <ul v-if="node.children.length && isOpen(node)" role="group" class="knowledge-nav-children">
      <KnowledgeNavigationBranch v-for="child in node.children" :key="child.id" :node="child" :depth="depth+1"
        :selected-id="selectedId" :is-open="isOpen" @select="emit('select',$event)" @toggle="emit('toggle',$event)" />
    </ul>
  </li>
</template>
<style scoped>
.knowledge-nav-item{list-style:none;min-width:0;scroll-margin:16px}
.knowledge-nav-row{display:flex;align-items:flex-start;gap:2px;min-width:0;border-radius:9px;margin:2px 0}
.knowledge-nav-toggle,.knowledge-nav-marker{flex:0 0 36px;width:36px;min-height:44px;display:grid;place-items:center;color:var(--text-secondary);border:0;background:transparent;font-size:21px;padding:0}
.knowledge-nav-title{flex:1;min-width:0;text-align:left;display:grid;gap:3px;padding:9px 6px;border:0;background:transparent;color:var(--text);line-height:1.5;border-radius:7px}
.knowledge-nav-title>span{font-size:14px;overflow-wrap:anywhere;white-space:normal}.is-branch>.knowledge-nav-row .knowledge-nav-title>span{font-weight:600}
.knowledge-nav-title small{font-size:11px;font-weight:400;color:var(--text-tertiary);line-height:1.45}
.knowledge-nav-view{flex:0 0 auto;margin:9px 4px 0 0;min-height:30px;padding:3px 7px;border:0;background:transparent;color:var(--text-secondary);font-size:11px}
.knowledge-nav-row:hover{background:#f3f5f1}.is-selected>.knowledge-nav-row{background:#e8eee2;box-shadow:inset 2px 0 #708667}
.knowledge-nav-title:focus-visible,.knowledge-nav-toggle:focus-visible,.knowledge-nav-view:focus-visible{outline:2px solid #768b6d;outline-offset:-2px}
.knowledge-nav-children{margin:0 0 5px 17px;padding:0 0 0 12px;border-left:1px solid #e1e5db;min-width:0}
@media(max-width:600px){.knowledge-nav-children{margin-left:6px;padding-left:5px}.knowledge-nav-toggle,.knowledge-nav-marker{flex-basis:30px;width:30px}.knowledge-nav-title>span{font-size:13px}.knowledge-nav-view{padding:3px;font-size:10px}}
</style>
