<script setup lang="ts">
import {onMounted} from 'vue';
import type {KnowledgeNodeView} from '../types/practice';
import KnowledgeScopeTree from './KnowledgeScopeTree.vue';
defineProps<{nodes:KnowledgeNodeView[];selectedIds:string[];selectedEntries:Array<{id:string;name:string}>;
 selectedCounts:ReadonlyMap<string,number>;expandedIds:ReadonlySet<string>;collapsedIds:ReadonlySet<string>;
 search:string;loading:boolean;error:string|null}>();
const emit=defineEmits<{load:[];'update:search':[value:string];toggle:[id:string];branch:[node:KnowledgeNodeView]}>();
onMounted(()=>emit('load'));
function searchChanged(event:Event){emit('update:search',(event.target as HTMLInputElement).value);}
</script>
<template>
 <div class="scope-editor-content" data-testid="scope-editor-content">
  <section class="scope-editor-selected" aria-label="当前已选知识点">
   <h3>当前已选知识点（{{selectedIds.length}}）</h3>
   <ul><li v-for="item in selectedEntries" :key="item.id"><span>{{item.name}}</span><button type="button" :aria-label="'移除'+item.name" @click="emit('toggle',item.id)">移除</button></li></ul>
   <p v-if="!selectedIds.length">尚未选择知识点。</p>
  </section>
  <section class="scope-editor-tree" aria-label="知识树">
   <h3>知识树</h3>
   <input type="search" :value="search" aria-label="搜索知识点" placeholder="搜索章节或知识点" @input="searchChanged"/>
   <p v-if="loading" role="status">正在加载知识树…</p>
   <div v-else-if="error" role="alert">{{error}}<button type="button" @click="emit('load')">重试</button></div>
   <div v-else class="scope-editor-tree-scroll" data-testid="scope-editor-tree-scroll" tabindex="0">
    <KnowledgeScopeTree :nodes="nodes" :selected-ids="selectedIds" :selected-counts="selectedCounts" :expanded-ids="expandedIds" :collapsed-ids="collapsedIds" :auto-expand="!!search.trim()" :level="1" checkbox-selection show-availability @toggle-selection="emit('toggle',$event)" @toggle-branch="emit('branch',$event)"/>
    <p v-if="!nodes.length">没有匹配的知识点。</p>
   </div>
  </section>
 </div>
</template>
<style scoped>
.scope-editor-content{display:grid;grid-template-rows:auto minmax(0,1fr);gap:12px;min-width:0;min-height:0;height:100%;overflow:hidden}.scope-editor-selected{max-height:24vh;overflow:auto}.scope-editor-selected ul{display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0;margin:0}.scope-editor-selected li{display:flex;align-items:center;gap:8px;max-width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:8px;overflow-wrap:anywhere}.scope-editor-tree{display:flex;flex-direction:column;min-height:0;min-width:0;gap:8px}.scope-editor-tree h3,.scope-editor-selected h3{margin:0 0 8px}.scope-editor-tree input{box-sizing:border-box;max-width:100%;min-height:40px;width:100%}.scope-editor-tree-scroll{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain}.scope-editor-selected button{flex-shrink:0;min-height:36px}@media(max-width:600px){.scope-editor-selected{max-height:22dvh}.scope-editor-selected li{width:100%;justify-content:space-between}}
</style>
