<script setup lang="ts">
import {nextTick,ref,watch} from 'vue';
import type {KnowledgeNodeView} from '../types/practice';
import KnowledgeNavigationBranch from './KnowledgeNavigationBranch.vue';
const props=defineProps<{nodes:KnowledgeNodeView[];selectedId:string|null;isOpen:(node:KnowledgeNodeView)=>boolean}>();
const emit=defineEmits<{select:[node:KnowledgeNodeView];toggle:[node:KnowledgeNodeView]}>();
const navigation=ref<HTMLElement|null>(null);
watch(()=>props.selectedId,()=>nextTick(()=>navigation.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'})));
defineExpose({resetView:()=>{if(navigation.value)navigation.value.scrollTop=0;}});
</script>
<template>
  <div ref="navigation" class="knowledge-navigation" data-testid="knowledge-navigation">
    <section v-for="root in nodes" :key="root.id" class="knowledge-subject" :aria-label="root.name">
      <template v-if="root.children.length">
        <h3><button type="button" :data-testid="`knowledge-node-${root.code}`" @click="emit('select',root)">{{root.name}}</button><small>学科</small></h3>
        <ul role="tree" :aria-label="`${root.name}章节`">
          <KnowledgeNavigationBranch v-for="node in root.children" :key="node.id" :node="node" :depth="0" :selected-id="selectedId" :is-open="isOpen" @select="emit('select',$event)" @toggle="emit('toggle',$event)" />
        </ul>
      </template>
      <ul v-else role="tree" :aria-label="root.name"><KnowledgeNavigationBranch :node="root" :depth="0" :selected-id="selectedId" :is-open="isOpen" @select="emit('select',$event)" @toggle="emit('toggle',$event)" /></ul>
    </section>
  </div>
</template>
<style scoped>
.knowledge-navigation{max-height:calc(100vh - 240px);min-height:240px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding:0 4px 16px 0}
.knowledge-subject{margin:14px 0 20px;min-width:0}.knowledge-subject h3{display:flex;align-items:baseline;gap:10px;margin:0 0 7px;padding:0 6px 8px;border-bottom:1px solid var(--border)}
.knowledge-subject h3 button{font-size:14px;font-weight:650;padding:3px 0;border:0;background:transparent;text-align:left;color:var(--text);overflow-wrap:anywhere}.knowledge-subject h3 small{font-size:10px;font-weight:400;color:var(--text-tertiary);white-space:nowrap}
ul{list-style:none;margin:0;padding:0;min-width:0}@media(max-width:900px){.knowledge-navigation{max-height:55vh;min-height:200px}}
</style>
