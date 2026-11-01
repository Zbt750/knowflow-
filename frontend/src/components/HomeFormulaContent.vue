<script setup lang="ts">
import {computed} from 'vue';
import MarkdownContent from './MarkdownContent.vue';
const props=defineProps<{text:string;label?:string}>();
const hasMath=computed(()=>/\$|\\\(|\\\[/.test(props.text));
</script>
<template>
 <div class="home-formula-scroll" :tabindex="hasMath?0:undefined" :role="hasMath?'region':undefined" :aria-label="hasMath?(label??'数学内容，可在区域内横向滚动'):undefined"><MarkdownContent :text="text"/></div>
</template>
<style scoped>
.home-formula-scroll{box-sizing:border-box;min-width:0;max-width:100%;overflow-x:auto;overscroll-behavior-x:contain}.home-formula-scroll:focus-visible{outline:2px solid var(--success,#4c6955);outline-offset:2px}.home-formula-scroll :deep(.markdown-content){min-width:0;max-width:100%}.home-formula-scroll :deep(.katex-display){max-width:100%;overflow-x:auto;overflow-y:hidden}.home-formula-scroll :deep(.katex){max-width:100%}
</style>
