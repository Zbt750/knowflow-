<script setup lang="ts">
import { computed } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

const props = defineProps<{ text: string }>();

// 问答和资料均来自可变文本；解析 Markdown 后先净化，再插入页面。
const html = computed(() => DOMPurify.sanitize(
  marked.parse(props.text, { gfm: true, breaks: true, async: false }) as string,
  { USE_PROFILES: { html: true }, FORBID_TAGS: ["img", "iframe", "style"] },
));
</script>

<template>
  <div class="markdown-content" v-html="html"></div>
</template>

<style scoped>
.markdown-content { min-width: 0; color: inherit; line-height: 1.75; overflow-wrap: anywhere; }
.markdown-content :deep(> :first-child) { margin-top: 0; }
.markdown-content :deep(> :last-child) { margin-bottom: 0; }
.markdown-content :deep(p) { margin: 0 0 .85em; white-space: normal; }
.markdown-content :deep(h1), .markdown-content :deep(h2), .markdown-content :deep(h3), .markdown-content :deep(h4) { margin: 1.25em 0 .5em; color: inherit; font-weight: 650; line-height: 1.45; }
.markdown-content :deep(h1) { font-size: 1.55em; }
.markdown-content :deep(h2) { font-size: 1.35em; }
.markdown-content :deep(h3) { font-size: 1.16em; }
.markdown-content :deep(ul), .markdown-content :deep(ol) { margin: .5em 0 1em; padding-left: 1.5em; }
.markdown-content :deep(li) { margin: .25em 0; }
.markdown-content :deep(blockquote) { margin: 1em 0; padding: .1em 0 .1em 1em; border-left: 3px solid #bfd4ec; color: var(--text-secondary); }
.markdown-content :deep(pre) { max-width: 100%; margin: 1em 0; padding: 12px 14px; overflow-x: auto; border: 1px solid #e3eaf2; border-radius: 10px; background: #f5f8fc; font-size: .9em; line-height: 1.6; }
.markdown-content :deep(pre code) { padding: 0; border: 0; background: transparent; white-space: pre; }
.markdown-content :deep(code) { padding: .12em .35em; border-radius: 5px; background: #f1f5fa; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .9em; }
.markdown-content :deep(a) { color: #245c9d; text-decoration: underline; text-underline-offset: 2px; }
.markdown-content :deep(hr) { height: 1px; margin: 1.3em 0; border: 0; background: var(--border); }
.markdown-content :deep(table) { display: block; max-width: 100%; margin: 1em 0; overflow-x: auto; border-collapse: collapse; }
.markdown-content :deep(th), .markdown-content :deep(td) { padding: 7px 9px; border: 1px solid var(--border); text-align: left; }
.markdown-content :deep(th) { background: #f5f8fc; }
</style>
