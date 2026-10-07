<script setup lang="ts">
import { computed, ref } from "vue";
import { fetchVisionSettings, saveVisionSettings, type VisionSettings } from "../api/vision";
const config = ref<VisionSettings | null>(null);
const reuse = ref(true), base = ref("https://api.deepseek.com"), model = ref("deepseek-flash");
const key = ref(""), clearKey = ref(false), tokens = ref(4000), timeout = ref(60);
const busy = ref(false), error = ref(""), notice = ref("");
const dirty = computed(() => config.value && (reuse.value !== config.value.reuse_chat_model
  || base.value !== config.value.base_url || model.value !== config.value.model
  || tokens.value !== config.value.max_output_tokens || timeout.value !== config.value.timeout_seconds || key.value || clearKey.value));
function fill(value: VisionSettings) {
  config.value = value; reuse.value = value.reuse_chat_model; base.value = value.base_url;
  model.value = value.model; tokens.value = value.max_output_tokens; timeout.value = value.timeout_seconds;
  key.value = ""; clearKey.value = false;
}
async function load() {
  if (busy.value) return;
  const preserve = dirty.value; busy.value = true; error.value = "";
  try { const value = await fetchVisionSettings(); if (preserve) config.value = value; else fill(value); }
  catch (e) { error.value = e instanceof Error ? e.message : "无法读取视觉配置"; }
  finally { busy.value = false; }
}
function open(event: Event) { if ((event.target as HTMLDetailsElement).open && !config.value) void load(); }
async function save() {
  if (!config.value || busy.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    fill(await saveVisionSettings({ reuse_chat_model: reuse.value, base_url: base.value.trim(), model: model.value.trim(),
      ...(key.value.trim() && !clearKey.value ? { api_key: key.value.trim() } : {}),
      clear_key: clearKey.value, max_output_tokens: tokens.value, timeout_seconds: timeout.value }, config.value.csrf_token));
    notice.value = "已保存。未发送测试图片；配置完整不代表识图效果已经验证。";
  } catch (e) { error.value = e instanceof Error ? e.message : "保存失败，原配置保留"; }
  finally { busy.value = false; }
}
</script>
<template>
  <details class="vision-settings" @toggle="open">
    <summary>拍照识别模型</summary>
    <p class="hint">可复用支持图片的问答模型，也可独立配置。密钥不会回显。</p>
    <form v-if="config" @submit.prevent="save">
      <fieldset :disabled="busy">
        <label class="reuse"><input v-model="reuse" type="checkbox" data-testid="vision-reuse" />复用当前问答模型配置</label>
        <template v-if="!reuse">
          <label>接口地址<input v-model="base" type="url" required maxlength="500" data-testid="vision-base-url" /></label>
          <label>模型名称<input v-model="model" required maxlength="120" data-testid="vision-model" /></label>
          <label>API 密钥<input v-model="key" type="password" autocomplete="new-password" maxlength="4096" :disabled="clearKey" :placeholder="config.key_configured ? '已保存 · 留空保持不变' : '填写密钥'" data-testid="vision-key" /></label>
          <label v-if="config.key_configured" class="reuse"><input v-model="clearKey" type="checkbox" />清除独立视觉密钥</label>
          <label>输出上限<input v-model.number="tokens" type="number" min="256" max="32768" required /></label>
          <label>超时（秒）<input v-model.number="timeout" type="number" min="5" max="180" required /></label>
        </template>
        <p v-if="config.storage_warning" role="alert">本地配置无法读取，识别已停用；请重新保存配置。</p>
        <div class="actions"><button type="submit">保存视觉配置</button><button type="button" @click="load">刷新配置</button></div>
      </fieldset>
    </form>
    <p v-if="busy && !config">正在读取…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error && !config" type="button" :disabled="busy" @click="load">重试读取</button>
    <p v-if="notice" role="status">{{ notice }}</p>
  </details>
</template>
<style scoped>
.vision-settings { padding: 20px 0; border-bottom: 1px solid var(--border); }
summary { cursor: pointer; font-size: 14px; }
.hint, p { color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
fieldset { border: 0; padding: 0; display: grid; gap: 14px; }
label { display: grid; gap: 6px; font-size: 13px; color: var(--text-secondary); }
input:not([type="checkbox"]) { min-width: 0; width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 9px; padding: 10px; background: white; }
.reuse, .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
