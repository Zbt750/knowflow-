<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { fetchHealth, type HealthResponse } from "../api/health";
import { fetchModelSettings, saveModelSettings, type ModelSettings } from "../api/settings";

const health = ref<HealthResponse | null>(null);
const loading = ref(false);
const error = ref("");
const config = ref<ModelSettings | null>(null);
const configError = ref("");
const saving = ref(false);
const notice = ref("");
const baseUrl = ref("");
const model = ref("");
const apiKey = ref("");
const clearKey = ref(false);
const maxTokens = ref(4000);
const timeout = ref(60);

const formDirty = computed(() => Boolean(config.value && (
  baseUrl.value !== config.value.base_url
  || model.value !== config.value.model
  || maxTokens.value !== config.value.max_output_tokens
  || timeout.value !== config.value.timeout_seconds
  || Boolean(apiKey.value)
  || clearKey.value
)));

function fillConfig(value: ModelSettings): void {
  config.value = value;
  baseUrl.value = value.base_url;
  model.value = value.model;
  maxTokens.value = value.max_output_tokens;
  timeout.value = value.timeout_seconds;
  apiKey.value = "";
  clearKey.value = false;
}

async function loadConfig(preserveDirty = false): Promise<void> {
  const keepForm = preserveDirty && formDirty.value;
  configError.value = "";
  try {
    const value = await fetchModelSettings();
    if (keepForm) config.value = value; // 更新授权令牌与状态，但保留用户正在编辑的字段/密钥。
    else fillConfig(value);
  }
  catch (caught) {
    if (!keepForm) config.value = null;
    configError.value = caught instanceof ApiError && caught.code === "settings_local_only"
      ? "模型配置仅限本机开发访问。Web 部署暂不开放密钥修改，请由管理员配置服务端。"
      : "读取模型配置失败，请刷新重试。";
  }
}

async function save(): Promise<void> {
  if (!config.value || saving.value) return;
  saving.value = true;
  notice.value = "";
  configError.value = "";
  try {
    const updated = await saveModelSettings({ base_url: baseUrl.value.trim(), model: model.value.trim(),
      ...(apiKey.value.trim() && !clearKey.value ? { api_key: apiKey.value.trim() } : {}),
      clear_key: clearKey.value, max_output_tokens: Number(maxTokens.value), timeout_seconds: Number(timeout.value),
    }, config.value.csrf_token);
    fillConfig(updated);
    notice.value = "已保存，下一次问答立即使用新配置。正在生成的回答不受影响。";
    await refresh(false);
  } catch (caught) {
    configError.value = caught instanceof ApiError && caught.code === "validation_failed" ? caught.message
      : caught instanceof ApiError && caught.code === "settings_token_invalid" ? "配置授权已失效，请刷新页面后再保存。"
      : "保存失败，原配置未更改。请检查服务状态后重试。";
  } finally { saving.value = false; }
}

async function refresh(includeConfig = true): Promise<void> {
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
    if (includeConfig) await loadConfig(true);
    loading.value = false;
  }
}

onMounted(() => void refresh());
</script>

<template>
  <section class="page settings-page">
    <header class="settings-heading">
      <div>
        <p>管理问答模型，查看本地服务状态。</p>
      </div>
      <button type="button" :disabled="loading || saving" @click="refresh()">{{ loading ? "检查中…" : "刷新状态" }}</button>
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
        <p class="settings-note">配置完整不代表上游连接已验证。已保存的密钥不会回显，也不存入浏览器。</p>
        <form v-if="config" class="model-form" @submit.prevent="save">
          <p v-if="config.storage_warning" role="alert" class="state state--error">本地配置无法读取，已停用旧密钥。请重新填写密钥并保存，其他功能仍可使用。</p>
          <fieldset :disabled="saving || loading">
            <label>接口地址<input v-model="baseUrl" type="url" maxlength="500" required placeholder="https://api.example.com/v1" data-testid="model-base-url" /></label>
            <label>模型名称<input v-model="model" maxlength="120" required placeholder="填写服务商提供的模型 ID" data-testid="model-name" /></label>
            <label>API 密钥<input v-model="apiKey" type="password" autocomplete="new-password" maxlength="4096" :disabled="clearKey" :placeholder="config.key_configured ? '已保存 · 留空保持不变' : '填写密钥'" data-testid="model-api-key" /></label>
            <label v-if="config.key_configured" class="clear-key"><input v-model="clearKey" type="checkbox" />移除已保存的密钥（保存后停用问答模型）</label>
            <div class="model-limits">
              <label>回答输出上限<input v-model.number="maxTokens" type="number" min="256" max="32768" step="1" required /></label>
              <label>请求超时（秒）<input v-model.number="timeout" type="number" min="5" max="180" step="1" required /></label>
            </div>
            <button type="submit" data-testid="save-model-settings">{{ saving ? '保存中…' : '保存配置' }}</button>
          </fieldset>
          <p class="settings-note">留空密钥会保留现有密钥。HTTPS 接口可远程使用；HTTP 仅允许本机接口。保存后无需重启后端。</p>
        </form>
        <p v-if="configError" class="state state--error" role="alert">{{ configError }}</p>
        <p v-if="notice" class="settings-note" role="status">{{ notice }}</p>
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
.model-form { margin-top: 20px; }
.model-form fieldset { padding: 0; margin: 0; border: 0; display: grid; gap: 16px; }
.model-form label { display: grid; gap: 7px; font-size: 13px; color: var(--text-secondary); }
.model-form input:not([type="checkbox"]) { width: 100%; min-width: 0; min-height: 40px; border: 1px solid var(--border); border-radius: 9px; padding: 9px 12px; background: #fff; color: var(--text); box-sizing: border-box; }
.model-form .clear-key { display: flex; align-items: center; font-size: 12px; }
.model-limits { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.model-form button { justify-self: start; }
@media (max-width: 520px) { .settings-section dl > div { grid-template-columns: 100px 1fr; } }
@media (max-width: 400px) { .model-limits { grid-template-columns: 1fr; } }
</style>
