<script setup lang="ts">
import frogKnowledgeRoots from '../assets/frog-knowledge-handstand-v4.png';
</script>

<template>
  <!-- 奶蛙是画布中的向导；具体知识节点仍由 KnowledgeTreeCanvas 按真实数据渲染。 -->
  <g class="frog-tree-figure" aria-hidden="true">
    <image
      class="frog-tree-mascot"
      :href="frogKnowledgeRoots"
      x="-355"
      y="-430"
      width="710"
      height="860"
      preserveAspectRatio="xMidYMid meet"
    />
    <ellipse class="frog-tree-eyelid" cx="-234" cy="86" rx="25" ry="30" />
    <ellipse class="frog-tree-eyelid frog-tree-eyelid--far" cx="-111" cy="28" rx="33" ry="30" />
  </g>
</template>

<style scoped>
.frog-tree-figure{pointer-events:none}
.frog-tree-mascot{transform-box:fill-box;transform-origin:center;animation:frog-root-breathe 7.4s ease-in-out infinite}
.frog-tree-eyelid{fill:#f2d05b;stroke:#d5b64a;stroke-width:2;opacity:0;transform-box:fill-box;transform-origin:center;animation:frog-tree-blink 6.8s ease-in-out -1.7s infinite}
.frog-tree-eyelid--far{animation-delay:-1.72s}
@keyframes frog-root-breathe{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-3px) scale(1.006)}}
@keyframes frog-tree-blink{0%,90%,100%{opacity:0;transform:scaleY(.04)}92%,94%{opacity:.98;transform:scaleY(1)}}
@media(prefers-reduced-motion:reduce){.frog-tree-mascot,.frog-tree-eyelid{animation:none;transform:none}.frog-tree-eyelid{opacity:0}}
</style>
