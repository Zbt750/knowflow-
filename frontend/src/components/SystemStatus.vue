<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, fetchHealth } from "../api/health";

type Status = "loading" | "ready" | "error";

const status = ref<Status>("loading");
const message = ref("正在检查后端与数据库连接…");
// 服务端稳定错误码；前端按 code 分支，不解析自然语言文案。
const errorCode = ref<string | null>(null);
let controller: AbortController | null = null;

async function refresh(): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  status.value = "loading";
  message.value = "正在检查后端与数据库连接…";
  errorCode.value = null;
  try {
    const health = await fetchHealth(controller.signal);
    status.value = "ready";
    message.value = `后端可用，PostgreSQL ${health.database}`;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    status.value = "error";
    // 统一用 client.ts 的 ApiError：`code` 决定行为、`message` 只当文案。
    // 后端不可达时 status 为 null（网络层失败），
    // 数据库不可用时 status 为 503 且 code=database_unavailable —— 两者要能分开。
    if (error instanceof ApiError) {
      message.value = error.message;
      errorCode.value = error.code;
    } else {
      message.value = "系统状态检查失败";
    }
  }
}

onMounted(() => void refresh());
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section
    class="system-status"
    :class="`system-status--${status}`"
    data-testid="system-status"
    :data-status="status"
    aria-live="polite"
  >
    <div>
      <strong>系统状态</strong>
      <p>{{ message }}</p>
      <p v-if="errorCode" class="system-status__code">错误码：{{ errorCode }}</p>
    </div>
    <button type="button" :disabled="status === 'loading'" @click="refresh">
      {{ status === "loading" ? "检查中" : "重新检查" }}
    </button>
  </section>
</template>
