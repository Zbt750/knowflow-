<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { fetchHealth, type HealthResponse } from "../api/health";

const health = ref<HealthResponse | null>(null);
const loading = ref(false);
const error = ref("");

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    health.value = await fetchHealth();
  } catch (caught) {
    health.value = null;
    if (caught instanceof ApiError && caught.code === "database_unavailable") {
      error.value = "后端已启动，但数据库不可用。请检查数据库服务与连接配置后重试。";
    } else if (caught instanceof ApiError && caught.status === null) {
      error.value = "无法连接后端服务，请确认后端已启动后重试。";
    } else if (caught instanceof ApiError) {
      error.value = `${caught.message}${caught.code ? `（${caught.code}）` : ""}`;
    } else {
      error.value = "读取服务状态失败，请稍后重试。";
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => void refresh());
</script>

<template>
  <section class="page settings-page">
    <header class="settings-heading">
      <div>
        <p>查看当前服务与问答模型状态。敏感配置只保存在服务端。</p>
      </div>
      <button type="button" :disabled="loading" @click="refresh">{{ loading ? "检查中…" : "刷新状态" }}</button>
    </header>

    <p v-if="error" class="state state--error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !health" class="state state--loading">正在读取配置状态…</p>

    <template v-if="health">
      <section class="settings-section">
        <h2>问答模型</h2>
        <dl>
          <div><dt>配置状态</dt><dd>{{ health.llm_configured ? "配置项已填写" : "尚未配置完整" }}</dd></div>
          <div><dt>模型</dt><dd>{{ health.llm_model || "未设置" }}</dd></div>
        </dl>
        <p class="settings-note">此状态只检查配置项是否填写，不代表上游服务一定可用。模型密钥和接口地址不会在网页里显示。</p>
        <p class="settings-note">如需调整，请在项目根目录的 <code>.env</code> 中设置 <code>LLM_API_KEY</code>、<code>LLM_BASE_URL</code> 和 <code>LLM_MODEL</code>，保存后重启后端，再刷新本页。</p>
      </section>

      <section class="settings-section">
        <h2>本地服务</h2>
        <dl>
          <div><dt>数据库</dt><dd>{{ health.database === "connected" ? "已连接" : "不可用" }}</dd></div>
          <div><dt>资料检索</dt><dd>{{ health.retrieval === "ready" ? "可用" : "不可用" }}</dd></div>
          <div><dt>后台处理</dt><dd>{{ health.worker === "running" ? "运行中" : "未运行" }}</dd></div>
          <div><dt>运行环境</dt><dd>{{ health.environment || "未知" }}</dd></div>
        </dl>
        <p class="settings-note">资料索引或问答异常时，可先在这里确认服务状态，再到 <RouterLink to="/materials">资料库</RouterLink> 查看具体资料。</p>
      </section>
    </template>
  </section>
</template>

<style scoped>
.settings-page { max-width: 820px; }
.settings-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
.settings-heading p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.settings-heading button { flex: 0 0 auto; }
.settings-section { padding: 21px 0; border-bottom: 1px solid var(--border); }
.settings-section h2 { margin: 0 0 14px; font-size: 16px; }
.settings-section dl { margin: 0; }
.settings-section dl > div { display: grid; grid-template-columns: 140px 1fr; gap: 12px; padding: 9px 0; }
.settings-section dt { color: var(--text-tertiary); }
.settings-section dd { margin: 0; color: var(--text); overflow-wrap: anywhere; }
.settings-note { max-width: 660px; margin: 13px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.75; }
.settings-note code { padding: 1px 4px; border-radius: 3px; background: #f3f3f3; }
.settings-note a { text-decoration: underline; }
@media (max-width: 520px) { .settings-section dl > div { grid-template-columns: 100px 1fr; } }
</style>
