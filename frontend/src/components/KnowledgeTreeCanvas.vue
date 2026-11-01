<script setup lang="ts">
import { computed, nextTick, onActivated, onDeactivated, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { KnowledgeNodeView } from '../types/practice';
import { layoutKnowledgeTree } from '../lib/knowledgeTreeLayout';
import FrogTreeFigure from './FrogTreeFigure.vue';

const props=defineProps<{nodes:KnowledgeNodeView[];selectedId:string|null;isOpen:(node:KnowledgeNodeView)=>boolean;limits:Record<string,number>;batchSize:number}>();
const emit=defineEmits<{select:[node:KnowledgeNodeView];toggle:[node:KnowledgeNodeView];more:[id:string]}>();
const viewport=ref<HTMLElement|null>(null);
const size=ref({width:typeof window==='undefined'?800:window.innerWidth,height:typeof window==='undefined'?650:window.innerHeight});
const compact=computed(()=>size.value.width<=620);
const graph=computed(()=>layoutKnowledgeTree(props.nodes,props.isOpen,props.limits,props.batchSize,compact.value,size.value.width));
const scale=ref(.7),pan=ref({x:0,y:0});
let observer:ResizeObserver|undefined;
let drag:{pointer:number;x:number;y:number}|null=null;
let interactionAnchor:string|null=null;
let measured=false;
let rootsSnapshot=props.nodes;
const worldStyle=computed(()=>({width:`${graph.value.width}px`,height:`${graph.value.height}px`,transform:graph.value.compact?'none':`translate(calc(-50% + ${pan.value.x}px),calc(-50% + ${pan.value.y}px)) scale(${scale.value})`,zoom:graph.value.compact?'0.62':'1'}));
const selectedAncestors=computed(()=>{
  const ids=new Set<string>();let row=graph.value.nodes.find(n=>!n.moreFor&&n.node.id===props.selectedId);
  while(row){ids.add(row.node.id);row=graph.value.nodes.find(n=>!n.moreFor&&n.node.id===row?.parentId)}
  return ids;
});
// 大章节允许平移探索，不能为塞下所有叶片而把文字缩成无法阅读的小点。
function fit(){
  if(graph.value.compact){scale.value=1;pan.value={x:0,y:0};if(viewport.value)viewport.value.scrollTop=0;return}
  scale.value=Math.max(.65,Math.min((size.value.width-32)/graph.value.width,(size.value.height-24)/Math.max(500,graph.value.height-120),1));pan.value={x:0,y:0}
}
defineExpose({ resetView: fit });
function toggleBranch(node:KnowledgeNodeView){interactionAnchor=node.id;emit('toggle',node)}
function selectEntry(node:KnowledgeNodeView){
  interactionAnchor=node.id;
  emit('select',node);
}
function selectJoint(id:string){const row=graph.value.nodes.find(row=>!row.moreFor&&row.node.id===id);if(row)selectEntry(row.node)}
function showMore(id:string){interactionAnchor=id;emit('more',id)}
function revealNode(id:string|null){
  const row=graph.value.nodes.find(n=>!n.moreFor&&n.node.id===id);if(!row)return;
  if(graph.value.compact){
    const view=viewport.value;if(!view)return;
    const top=row.y-rowHeight/2-view.scrollTop,bottom=row.y+rowHeight/2-view.scrollTop;
    if(top<14)view.scrollTop=Math.max(0,view.scrollTop+top-14);
    else if(bottom>view.clientHeight-14)view.scrollTop+=bottom-view.clientHeight+14;
    return;
  }
  const x=(row.x-graph.value.width/2)*scale.value+size.value.width/2+pan.value.x;
  const y=(row.y-graph.value.height/2)*scale.value+size.value.height/2+pan.value.y;
  const margin=Math.min(115,size.value.width/4);
  pan.value={x:pan.value.x+(x<margin?margin-x:x>size.value.width-margin?size.value.width-margin-x:0),y:pan.value.y+(y<60?60-y:y>size.value.height-60?size.value.height-60-y:0)};
}
function revealBranch(id:string|null){
  if(!id)return;
  const rows=graph.value.nodes.filter(row=>row.node.id===id||row.parentId===id);
  if(!rows.length)return;
  if(graph.value.compact){
    const view=viewport.value;if(!view)return;
    const top=Math.min(...rows.map(row=>row.y-rowHeight/2));
    const bottom=Math.max(...rows.map(row=>row.y+rowHeight/2));
    if(bottom-top<view.clientHeight-24){
      if(top<view.scrollTop+12)view.scrollTop=Math.max(0,top-12);
      else if(bottom>view.scrollTop+view.clientHeight-12)view.scrollTop=bottom-view.clientHeight+12;
    }
    return;
  }
  const xs=rows.map(row=>(row.x-graph.value.width/2)*scale.value+size.value.width/2+pan.value.x);
  const ys=rows.map(row=>(row.y-graph.value.height/2)*scale.value+size.value.height/2+pan.value.y);
  const left=Math.min(...xs)-100*scale.value,right=Math.max(...xs)+100*scale.value;
  const top=Math.min(...ys)-30*scale.value,bottom=Math.max(...ys)+30*scale.value;
  // 能放下时把当前分支完整移入视口；超大分支仍保留操作点，通过平移浏览。
  const dx=right-left<size.value.width-32?(left<16?16-left:right>size.value.width-16?size.value.width-16-right:0):0;
  const dy=bottom-top<size.value.height-32?(top<16?16-top:bottom>size.value.height-16?size.value.height-16-bottom:0):0;
  pan.value={x:pan.value.x+dx,y:pan.value.y+dy};
}
const rowHeight=94;
function revealFirstVisibleNode(){
  const rows=graph.value.nodes.filter(row=>!row.moreFor);
  const focus=rows.reduce<(typeof rows)[number]|null>((best,row)=>!best||row.depth>best.depth?row:best,null);
  if(focus)revealNode(focus.node.id);
}
function onPointerDown(event:PointerEvent){if(event.button!==0||(event.target as Element).closest('button,a,input,.knowledge-tree-entry'))return;drag={pointer:event.pointerId,x:event.clientX-pan.value.x,y:event.clientY-pan.value.y};viewport.value?.setPointerCapture(event.pointerId)}
function onPointerMove(event:PointerEvent){if(!drag)return;pan.value={x:event.clientX-drag.x,y:event.clientY-drag.y}}
function onWheel(event:WheelEvent){
  if(graph.value.compact)return;
  event.preventDefault();pan.value={x:pan.value.x-event.deltaX,y:pan.value.y-event.deltaY};
}
function endDrag(){drag=null}
function onKey(event:KeyboardEvent){if(event.target!==viewport.value)return;const shifts:Record<string,[number,number]>={ArrowLeft:[45,0],ArrowRight:[-45,0],ArrowUp:[0,45],ArrowDown:[0,-45]};const shift=shifts[event.key];if(shift){event.preventDefault();pan.value={x:pan.value.x+shift[0],y:pan.value.y+shift[1]}}}
const nodeStatus=(node:KnowledgeNodeView)=>node.is_reference_only?'题源索引 · 非考核':node.post_graduation?.applicable?'已毕业 · '+node.post_graduation.label:node.is_assessable?(node.state==='mastered'?'已掌握':node.state==='unseen'||!node.state?'未开始':'学习中'):`${node.children.length} 个下级分支`;
watch(()=>props.selectedId,()=>nextTick(()=>{if(props.selectedId){revealNode(props.selectedId);revealBranch(interactionAnchor??props.selectedId)}}));
watch(graph,(next,previous)=>{
  // 搜索/切换学科重新适配；仅展开分支时保留缩放和操作点，避免整棵树反复跳动。
  if(rootsSnapshot!==props.nodes){rootsSnapshot=props.nodes;nextTick(()=>{fit();if(props.selectedId&&next.nodes.some(row=>!row.moreFor&&row.node.id===props.selectedId))revealNode(props.selectedId);else revealFirstVisibleNode()});return}
  const anchor=interactionAnchor??props.selectedId;
  const before=previous.nodes.find(row=>!row.moreFor&&row.node.id===anchor);
  const after=next.nodes.find(row=>!row.moreFor&&row.node.id===anchor);
  if(before&&after){pan.value={
    x:pan.value.x+((before.x-previous.width/2)-(after.x-next.width/2))*scale.value,
    y:pan.value.y+((before.y-previous.height/2)-(after.y-next.height/2))*scale.value,
  }}
  nextTick(()=>{
    if(props.selectedId&&next.nodes.some(row=>!row.moreFor&&row.node.id===props.selectedId)){
      revealNode(props.selectedId);revealBranch(anchor);
    }else revealFirstVisibleNode();
  });
});
onMounted(()=>{observer=new ResizeObserver(entries=>{const r=entries[0]?.contentRect;if(r){const previousCompact=compact.value;const widthChanged=Math.abs(size.value.width-r.width)>32;size.value={width:r.width,height:r.height};if(!measured||widthChanged||previousCompact!==compact.value){fit();measured=true;nextTick(()=>{if(props.selectedId&&graph.value.nodes.some(row=>!row.moreFor&&row.node.id===props.selectedId)){revealNode(props.selectedId);revealBranch(interactionAnchor??props.selectedId)}else revealFirstVisibleNode()})}else if(props.selectedId){revealNode(props.selectedId)}}});if(viewport.value)observer.observe(viewport.value)});
onBeforeUnmount(()=>observer?.disconnect());
onDeactivated(()=>{observer?.disconnect();drag=null;});
onActivated(()=>{if(observer&&viewport.value)observer.observe(viewport.value);});
</script>

<template>
  <section class="knowledge-canvas" aria-label="奶蛙树形知识导航">
    <div ref="viewport" class="knowledge-canvas-viewport" :class="{'knowledge-canvas-viewport--compact':graph.compact}" tabindex="0" aria-label="知识树画布，可拖动或滚动浏览；方向键平移" data-testid="knowledge-canvas" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag" @keydown="onKey" @wheel="onWheel">
      <div class="knowledge-canvas-world" :class="{'knowledge-canvas-world--compact':graph.compact}" :style="worldStyle" role="tree" aria-label="真实知识层级">
        <svg class="canvas-branches" :viewBox="`0 0 ${graph.width} ${graph.height}`" aria-hidden="true"><g :transform="`translate(${graph.width/2},${graph.compact?graph.figureY:graph.height/2}) scale(${graph.figureScale})`"><FrogTreeFigure /></g><path v-for="edge in graph.edges" :key="edge.key" :d="edge.d" :class="{'on-path':selectedAncestors.has(edge.targetId),'frog-limb':edge.isRoot,'frog-toe':!edge.isRoot}"/></svg>
        <button v-for="edge in graph.edges.filter(edge=>!edge.key.startsWith('more-')&&graph.nodes.some(row=>!row.moreFor&&row.node.id===edge.targetId))" :key="`joint-${edge.key}`" type="button" class="canvas-joint-control" :class="{'root-joint':edge.isRoot,'on-path':selectedAncestors.has(edge.targetId)}" :style="{left:`${edge.jointX}px`,top:`${edge.jointY}px`}" :aria-label="`选择或展开${graph.nodes.find(row=>row.node.id===edge.targetId)?.node.name}`" :data-testid="`tree-joint-${edge.targetId}`" @click.stop="selectJoint(edge.targetId)"><span aria-hidden="true">{{selectedAncestors.has(edge.targetId)?'●':'·'}}</span></button>
        <div v-for="row in graph.nodes" :key="row.key" class="knowledge-tree-entry" :class="{'entry-root':row.depth===0,'entry-toe':row.depth===1,'entry-leaf':row.node.is_assessable,'entry-reference':row.node.is_reference_only,'entry-selected':!row.moreFor&&selectedId===row.node.id,'entry-path':selectedAncestors.has(row.node.id)}" :style="{left:`${row.x}px`,top:`${row.y}px`}" role="treeitem" :aria-level="row.depth+1" :aria-expanded="!row.moreFor&&row.node.children.length?isOpen(row.node):undefined" @click="!row.moreFor && selectEntry(row.node)">
          <button v-if="row.moreFor" type="button" class="canvas-more" :aria-label="`显示更多${row.node.name}下的节点`" @click.stop="showMore(row.moreFor)">显示更多 <small>还有 {{row.remaining}} 项</small></button>
          <template v-else><div class="canvas-node-row"><button v-if="row.node.children.length" type="button" class="canvas-toggle" :aria-label="isOpen(row.node)?`收起${row.node.name}`:`展开${row.node.name}`" @click.stop="toggleBranch(row.node)">{{isOpen(row.node)?'−':'＋'}}</button><span v-else class="canvas-leaf-mark" :class="{'completed':row.node.post_graduation?.applicable,'learning':row.node.state&&row.node.state!=='unseen'}" aria-hidden="true"></span><button type="button" class="canvas-node-name" :aria-current="selectedId===row.node.id?'true':undefined" :data-testid="`tree-node-${row.node.code}`" @click.stop="selectEntry(row.node)">{{row.node.name}}</button></div><small class="canvas-node-status">{{nodeStatus(row.node)}}</small></template>
        </div>
      </div>
    </div>
    <footer class="canvas-legend"><span><i></i>考核知识点</span><span><i class="done"></i>已正式毕业</span><span><i class="reference"></i>题源导航</span><small>拖动或滚动浏览 · 点击章节展开</small></footer>
  </section>
</template>

<style scoped>
.canvas-branches>path.frog-limb{stroke:#e8bd52;stroke-width:25;stroke-linecap:round}
.canvas-branches>path.frog-toe{stroke:#d7c483;stroke-width:10;stroke-linecap:round}
.canvas-branches>path.on-path{stroke:#d4ac3f}
.canvas-joint-control{position:absolute;z-index:3;transform:translate(-50%,-50%);width:40px;height:40px;min-height:40px;padding:0;border:2px solid #d4b65f;border-radius:50%;background:#f5dfa0;color:#796b39;box-shadow:none;cursor:pointer;line-height:1}
.canvas-joint-control.root-joint{width:46px;height:46px;min-height:46px;background:#edc95f}
.canvas-joint-control:hover,.canvas-joint-control:focus-visible{background:#ffe7a1;outline:3px solid #becdad;outline-offset:2px}
.canvas-joint-control.on-path{border-color:#718960}
.knowledge-canvas-viewport--compact{overflow-x:hidden;overflow-y:auto;touch-action:pan-y;cursor:auto;overscroll-behavior:contain;max-height:min(46vh,360px)}
.knowledge-canvas-world.knowledge-canvas-world--compact{left:0;top:0;transform-origin:top left;will-change:auto}
.knowledge-canvas-world--compact .knowledge-tree-entry{width:min(300px,calc(100% - 32px));min-height:68px;padding:8px 10px}
.knowledge-canvas-world--compact .canvas-node-name{font-size:16px;line-height:1.35}
.knowledge-canvas-world--compact .canvas-node-status{padding-left:39px;font-size:11px}
.knowledge-canvas-world--compact .canvas-branches>path.frog-limb{stroke-width:11}
.knowledge-canvas-world--compact .canvas-branches>path.frog-toe{stroke-width:4}
</style>

<style scoped>
.knowledge-canvas{background:var(--background,#fcfbf7);border-top:1px solid var(--border);min-width:0}.canvas-tools{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 14px;border-bottom:1px solid var(--border);font-size:11px;color:var(--text-tertiary)}.canvas-tools>div{display:flex;align-items:center;gap:6px}.canvas-tools button{min-height:27px;padding:3px 8px;background:transparent;font-size:11px}.canvas-tools>div>span{min-width:34px;text-align:center;font-variant-numeric:tabular-nums}.knowledge-canvas-viewport{position:relative;overflow:hidden;height:clamp(560px,calc(100dvh - 255px),850px);touch-action:none;cursor:grab;outline-offset:-3px}.knowledge-canvas-viewport:active{cursor:grabbing}.knowledge-canvas-world{position:absolute;left:50%;top:50%;transform-origin:center;will-change:transform}.canvas-branches{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.canvas-branches>path{fill:none;stroke:#a5b59b;stroke-width:2;stroke-linecap:round}.canvas-branches>path.on-path{stroke:#728e60;stroke-width:3}.canvas-joint{fill:#829c72;stroke:#fcfbf7;stroke-width:2}.canvas-joint.root-joint{fill:#cbb464}.canvas-joint.on-path{fill:#55784d;stroke:#e8efdf}.knowledge-tree-entry{position:absolute;width:230px;min-height:68px;transform:translate(-50%,-50%);z-index:1;background:#fcfbf7f5;color:#536a4b;border-bottom:1px solid #ced8c4;border-radius:5px;padding:8px 10px}.canvas-node-row{display:flex;align-items:center;gap:7px}.canvas-toggle{flex:0 0 32px;min-height:34px;padding:0;border:0;background:transparent;color:#8e9c7d;font-size:21px}.canvas-node-name{border:0;background:transparent;text-align:left;padding:5px 0;min-height:36px;color:inherit;font-size:17px;line-height:1.35;overflow-wrap:anywhere}.canvas-node-name:hover:not(:disabled),.canvas-toggle:hover:not(:disabled){background:transparent;color:#364f2f}.canvas-node-status{display:block;padding-left:39px;font-size:12px;color:#99a28b;line-height:1.5}.entry-root{background:#fcfbf7;border-color:#b9c7a7}.entry-root .canvas-node-name{font-family:'Songti SC','SimSun',serif;font-size:21px}.entry-selected{background:#f0f3e7;border-color:#92a680;border-radius:8px}.entry-reference{border:1px dashed #c9c9b0;color:#92957b}.canvas-leaf-mark{flex:0 0 13px;width:13px;height:8px;margin:0 9px 0 8px;border-radius:12px 1px 12px 1px;background:#c1cfb6}.canvas-leaf-mark.learning{background:#d1bd78}.canvas-leaf-mark.completed{background:#74966a}.canvas-more{display:block;width:100%;border:0;background:transparent;color:#819272;text-align:left;font-size:15px}.canvas-more small{display:block;font-size:12px;margin-top:4px}.canvas-legend{display:flex;gap:13px;align-items:center;min-height:40px;padding:9px 13px;border-top:1px solid var(--border);font-size:10px;color:#8b977e}.canvas-legend>span{display:flex;align-items:center;gap:4px}.canvas-legend i{width:9px;height:6px;border-radius:9px 1px;background:#bfceb1}.canvas-legend i.done{background:#74966a}.canvas-legend i.reference{border:1px dashed #bcbfa4;background:none}.canvas-legend>small{margin-left:auto;font-size:10px}.entry-path:not(.entry-selected){border-bottom-color:#9eb38b}@media(max-width:620px){.canvas-tools{flex-wrap:wrap}.knowledge-canvas-viewport{height:520px}.canvas-legend{flex-wrap:wrap}.canvas-legend>small{margin-left:0}}@media(prefers-reduced-motion:reduce){.knowledge-canvas-world{will-change:auto}}
</style>
