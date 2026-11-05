import { computed, ref } from "vue";

const globalFailure = ref(false);

export const hasGlobalFailure = computed(() => globalFailure.value);

export function reportGlobalFailure(error: unknown, info: string): void {
  // 开发者需要完整上下文；学习者只需要一个明确、可恢复的界面。
  console.error("未捕获的前端异常", { error, info });
  globalFailure.value = true;
}

export function clearGlobalFailure(): void {
  globalFailure.value = false;
}