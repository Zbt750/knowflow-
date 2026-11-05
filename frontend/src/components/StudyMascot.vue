<script setup lang="ts">
import { computed, useId } from 'vue';
import { mascotEyeLids, mascotPropPoses, poseLibrary } from '../lib/mascotPoses';
import image from '../assets/study-frog-poses-v1.png';
const props=withDefaults(defineProps<{pose?:keyof typeof poseLibrary}>(),{pose:'read'});
const id=`mascot-${useId().replace(/[^a-zA-Z0-9_-]/g,'')}`;
const item=computed(()=>poseLibrary[props.pose]);
const outlines=computed(()=>item.value.path.split(/(?= M)/));
const eyelids=computed(()=>mascotEyeLids[props.pose] ?? []);
const movesHeldObject=computed(()=>mascotPropPoses.has(props.pose));
// 在屏幕坐标上做很轻的呼吸起伏；不同姿势、不同实例错开节奏，
// 让角色在页面里有生命感，但不干扰阅读和做题。
const motionStyle=computed(()=>{
  const poseIndex=Object.keys(poseLibrary).indexOf(props.pose);
  const phase=Array.from(id).reduce((total,char)=>total+char.charCodeAt(0),0);
  return {
    '--mascot-idle-duration':`${5.8+poseIndex*.42}s`,
    '--mascot-idle-delay':`${-(phase%60)/10}s`,
    '--mascot-blink-delay':`${-(phase%70)/10}s`,
    '--mascot-prop-delay':`${-(phase%50)/10}s`,
  };
});
</script>
<template>
  <svg class="study-mascot" :viewBox="item.box.join(' ')" :style="motionStyle" aria-hidden="true" focusable="false">
    <defs><clipPath :id="id"><path v-for="(path,i) in outlines" :key="i" :d="path.trim()"/></clipPath><clipPath :id="`${id}-floor`"><rect width="1536" :height="pose==='teach'?699:1024"/></clipPath></defs>
    <g class="mascot-breathe" :class="{'mascot-prop-motion':movesHeldObject}" :clip-path="`url(#${id}-floor)`"><image :href="image" width="1536" height="1024" :clip-path="`url(#${id})`"/></g>
    <g class="mascot-blinks" aria-hidden="true"><ellipse v-for="(eye,index) in eyelids" :key="index" class="mascot-eyelid" :cx="eye.cx" :cy="eye.cy" :rx="eye.rx" :ry="eye.ry"/></g>
  </svg>
</template>
<style scoped>
.study-mascot{display:block;width:112px;height:106px;flex:0 0 auto;pointer-events:none;overflow:visible;transform-origin:50% 95%;animation:mascot-idle var(--mascot-idle-duration,7s) ease-in-out var(--mascot-idle-delay,0s) infinite}
.mascot-breathe{transform-box:fill-box;transform-origin:50% 70%}
.mascot-prop-motion{animation:mascot-held-object var(--mascot-idle-duration,7s) ease-in-out var(--mascot-prop-delay,0s) infinite}
.mascot-eyelid{fill:#f2d05b;stroke:#d5b64a;stroke-width:2;opacity:0;transform-box:fill-box;transform-origin:center;animation:mascot-blink 6.4s ease-in-out var(--mascot-blink-delay,0s) infinite}
@keyframes mascot-idle{0%,100%{transform:translateY(0) rotate(-.35deg) scale(1)}50%{transform:translateY(-3.5px) rotate(.55deg) scale(1.008)}}
@keyframes mascot-held-object{0%,100%{transform:translateY(0) rotate(-.18deg)}50%{transform:translateY(-1.5px) rotate(.45deg)}}
@keyframes mascot-blink{0%,90%,100%{opacity:0;transform:scaleY(.04)}92%,94%{opacity:.98;transform:scaleY(1)}}
@media(prefers-reduced-motion:reduce){.study-mascot,.mascot-prop-motion,.mascot-eyelid{animation:none;transform:none}.mascot-eyelid{opacity:0}}
</style>
