<script setup lang="ts">
import { computed, onErrorCaptured, ref } from "vue";

import { clearGlobalFailure, hasGlobalFailure } from "../lib/runtimeErrors";

const localFailure = ref(false);
const retryKey = ref(0);
const failed = computed(() => localFailure.value || hasGlobalFailure.value);

onErrorCaptured((error, _instance, info) => {
  // 页面异常必须留在控制台供开发定位，但不能把原始堆栈暴露给学习者。
  console.error("页面组件渲染失败", { error, info });
  localFailure.value = true;
  // 已在此处转成可恢复的界面，不再向上传播成整页白屏。
  return false;
});

function retry(): void {
  localFailure.value = false;
  clearGlobalFailure();
  retryKey.value += 1;
}
</script>

<template>
  <section v-if="failed" class="error-boundary" data-testid="global-error-boundary" role="alert">
    <p class="eyebrow">页面需要重新加载</p>
    <h1>这一部分暂时没有正确显示</h1>
    <p>你的学习数据没有被修改。你可以先重新载入当前页面；若问题持续出现，请稍后再试。</p>
    <button type="button" class="button-primary" @click="retry">重新加载当前页面</button>
  </section>
  <div v-else :key="retryKey" class="route-content"><slot /></div>
</template>