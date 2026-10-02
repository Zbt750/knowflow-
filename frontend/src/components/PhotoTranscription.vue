<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { recognizeWork } from "../api/vision";
import MarkdownContent from "./MarkdownContent.vue";
const props = defineProps<{ itemId: string; disabled?: boolean; hasText: boolean }>();
const emit = defineEmits<{ apply: [text: string] }>();
const file = ref<File | null>(null), preview = ref(""), consent = ref(false), draft = ref("");
const error = ref(""), busy = ref(false), replace = ref(false);
const codePreview = ref(false);
const input = ref<HTMLInputElement | null>(null);
let controller: AbortController | null = null;
let generation = 0;
function reset() {
  generation++; controller?.abort(); controller = null;
  if (preview.value) URL.revokeObjectURL(preview.value);
  file.value = null; preview.value = ""; draft.value = ""; consent.value = false; busy.value = false; replace.value = false;
  codePreview.value = false;
  if (input.value) input.value.value = "";
}
function select(event: Event) {
  const picked = (event.target as HTMLInputElement).files?.[0]; reset(); error.value = "";
  if (!picked) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(picked.type) || picked.size > 5 * 1024 * 1024) {
    error.value = "请选择5MB以内的JPEG、PNG或WebP图片。"; return;
  }
  file.value = picked; preview.value = URL.createObjectURL(picked);
}
async function recognize() {
  if (!file.value || !consent.value || busy.value || props.disabled) return;
  const current = ++generation; controller = new AbortController(); busy.value = true; error.value = "";
  try { const result = await recognizeWork(props.itemId, file.value, controller.signal);
    if (current === generation) {
      draft.value = result.text; replace.value = false;
      codePreview.value = /^\s*(?:while |for |if |def |return |else\s*:)/m.test(result.text);
    }
  } catch (e) {
    if (current === generation && !(e instanceof DOMException && e.name === 'AbortError')) error.value = e instanceof Error ? e.message : "识别失败";
  } finally { if (current === generation) busy.value = false; }
}
function apply() {
  if (busy.value || props.disabled || !draft.value.trim() || (props.hasText && !replace.value)) return;
  emit('apply', draft.value.trim()); reset(); error.value = "";
}
watch(() => props.itemId, () => { reset(); error.value = ""; });
onBeforeUnmount(reset);
</script>
<template>
  <details class="photo-transcription">
    <summary>从照片录入过程</summary>
    <input ref="input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" aria-label="拍照或选择解题过程图片" :disabled="busy || disabled" @change="select" />
    <template v-if="file">
      <img :src="preview" alt="待识别的过程图片预览" />
      <label><input v-model="consent" type="checkbox" :disabled="busy || disabled" />同意将这张图片发送到已配置的视觉模型（可能产生费用）</label>
      <p>仅支持5MB以内的静态图片，边长不超过4096像素、总像素不超过1200万。识别不会判题，也不自动审阅；请核对文字和公式。</p>
      <div class="actions"><button type="button" :disabled="busy || disabled || !consent" @click="recognize">{{ busy ? '正在识别…' : '识别图片' }}</button><button type="button" @click="reset">{{ busy ? '取消等待' : '移除图片' }}</button></div>
      <p v-if="busy">取消等待不保证撤销上游已经开始的调用。</p>
    </template>
    <template v-if="draft">
      <textarea v-model="draft" rows="5" maxlength="4000" aria-label="识别结果，确认前可修改" :disabled="busy || disabled" />
      <details class="transcription-preview">
        <summary>预览文字与公式</summary>
        <label><input v-model="codePreview" type="checkbox" />按代码预览，保留缩进</label>
        <pre v-if="codePreview" class="code-preview">{{ draft }}</pre>
        <MarkdownContent v-else :text="draft" />
      </details>
      <label v-if="hasText"><input v-model="replace" type="checkbox" />用已核对的识别结果替换下方现有过程</label>
      <button type="button" :disabled="busy || disabled || !draft.trim() || (hasText && !replace)" @click="apply">确认并填入过程</button>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </details>
</template>
<style scoped>
.photo-transcription { margin: 12px 0; font-size: 12px; color: var(--text-secondary); }
summary { cursor: pointer; margin-bottom: 10px; }
img { display: block; max-width: min(100%, 360px); max-height: 260px; object-fit: contain; border-radius: 10px; margin: 12px 0; }
label { display: flex; gap: 7px; align-items: flex-start; }
p { color: var(--text-tertiary); line-height: 1.6; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
textarea { width: 100%; box-sizing: border-box; border-radius: 12px; margin: 12px 0; resize: vertical; }
.code-preview { max-width: 100%; overflow-x: auto; white-space: pre; padding: 12px; border-radius: 10px; background: #f7f8fa; color: var(--text-secondary); }
</style>
