<script setup lang="ts">
import { onBeforeUnmount, ref, toRef, watch } from "vue";
import type { ProcessReviewState } from "../api/study";
import { recognizeWork } from "../api/vision";
import MarkdownContent from "./MarkdownContent.vue";
import { photoFileError, photoDimensionsError } from "../lib/photoInput";
const props = defineProps<{ itemId: string; disabled?: boolean; hasText: boolean; state: Pick<ProcessReviewState, "photoDraft"> }>();
const emit = defineEmits<{ apply: [text: string] }>();
const file = ref<File | null>(null), preview = ref(""), consent = ref(false);
// Only text survives view switches. Image/object URL/consent and requests remain ephemeral.
const draft = toRef(props.state, "photoDraft");
const error = ref(""), busy = ref(false), replace = ref(false);
const codePreview = ref(false);
const checking = ref(false);
const input = ref<HTMLInputElement | null>(null);
const photoDialog = ref<HTMLDialogElement | null>(null);
const zoom = ref(100);
function openPhoto() {
  if (!preview.value || checking.value || !photoDialog.value) return;
  zoom.value = 100;
  photoDialog.value.showModal();
}
function closePhoto() { photoDialog.value?.close(); }
function keepPhotoFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !photoDialog.value) return;
  const controls = Array.from(photoDialog.value.querySelectorAll<HTMLElement>(
    'button:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
  )).filter(element => element.getClientRects().length > 0);
  const first = controls[0], last = controls[controls.length - 1];
  if (!first || !last) return;
  const active = document.activeElement;
  if (!controls.includes(active as HTMLElement) || (event.shiftKey ? active === first : active === last)) {
    event.preventDefault(); (event.shiftKey ? last : first).focus();
  }
}
let controller: AbortController | null = null;
let generation = 0;
let selectionGeneration = 0;
function cancelWaiting() {
  generation++; controller?.abort(); controller = null; busy.value = false;
  // Keep the selected image and the user's checked draft; late responses are ignored.
}
function reset(clearDraft = true) {
  closePhoto(); zoom.value = 100;
  selectionGeneration++; checking.value = false;
  cancelWaiting(); error.value = "";
  if (preview.value) URL.revokeObjectURL(preview.value);
  file.value = null; preview.value = ""; consent.value = false; busy.value = false; replace.value = false;
  if (clearDraft) draft.value = "";
  codePreview.value = false;
  if (input.value) input.value.value = "";
}
async function select(event: Event) {
  const target = event.target as HTMLInputElement;
  const picked = target.files?.[0];
  if (!picked) return;
  const invalid = photoFileError(picked);
  if (invalid) { error.value = invalid; target.value = ''; return; }
  const selection = ++selectionGeneration;
  const candidate = URL.createObjectURL(picked);
  checking.value = true; error.value = '';
  try {
    const image = new Image(); image.src = candidate;
    await image.decode();
    if (selection !== selectionGeneration) return;
    const dimensionsError = photoDimensionsError(image.naturalWidth, image.naturalHeight);
    if (dimensionsError) { error.value = dimensionsError; target.value = ''; return; }
    // Only replace the current image/draft after the new file passed local checks.
    reset(); file.value = picked; preview.value = URL.createObjectURL(picked);
  } catch {
    if (selection === selectionGeneration) {
      error.value = '无法读取图片，请另选一张JPEG、PNG或WebP图片。'; target.value = '';
    }
  } finally {
    URL.revokeObjectURL(candidate);
    if (selection === selectionGeneration) checking.value = false;
  }
}
async function recognize() {
  if (!file.value || !consent.value || busy.value || checking.value || props.disabled) return;
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
  if (busy.value || checking.value || props.disabled || !draft.value.trim() || (props.hasText && !replace.value)) return;
  emit('apply', draft.value.trim()); reset(); error.value = "";
}
watch(() => props.itemId, () => { reset(); error.value = ""; });
onBeforeUnmount(() => reset(false));
</script>
<template>
  <details class="photo-transcription">
    <summary>从照片录入过程</summary>
    <input ref="input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" aria-label="拍照或选择解题过程图片" :disabled="busy || checking || disabled" @change="select" />
    <p v-if="checking" role="status">正在检查图片…</p>
    <template v-if="file">
      <img :src="preview" alt="待识别的过程图片预览" />
      <button type="button" :disabled="checking" @click="openPhoto">放大核对</button>
      <Teleport to="body">
        <dialog ref="photoDialog" class="photo-review" aria-label="照片与识别文字核对" @click.self="closePhoto" @keydown="keepPhotoFocus">
          <div class="photo-review-toolbar">
            <div class="photo-zoom">
              <button type="button" aria-label="缩小照片" :disabled="zoom <= 100" @click="zoom -= 25">−</button>
              <span aria-live="polite">{{ zoom }}%</span>
              <button type="button" aria-label="放大照片" :disabled="zoom >= 300" @click="zoom += 25">+</button>
              <button type="button" :disabled="zoom === 100" @click="zoom = 100">适应窗口</button>
            </div>
            <button type="button" autofocus @click="closePhoto">关闭核对</button>
          </div>
          <div class="photo-review-layout">
            <div class="photo-review-image" tabindex="0" role="region" aria-label="原图，可滚动查看">
              <img class="review-original" :src="preview" alt="核对用原图" :style="{ width: `${zoom}%` }" />
            </div>
            <textarea v-if="draft" v-model="draft" maxlength="4000" aria-label="对照原图修改识别文字" :disabled="busy || checking || disabled" />
            <p v-else>识别完成后，可在这里对照原图修改文字。</p>
          </div>
        </dialog>
      </Teleport>
      <label><input v-model="consent" type="checkbox" :disabled="busy || disabled" />同意将这张图片发送到已配置的视觉模型（可能产生费用）</label>
      <p>仅支持5MB以内的静态图片，边长不超过4096像素、总像素不超过1200万。识别不会判题，也不自动审阅；请核对文字和公式。</p>
      <div class="actions"><button type="button" :disabled="busy || checking || disabled || !consent" @click="recognize">{{ busy ? '正在识别…' : '识别图片' }}</button><button type="button" @click="busy ? cancelWaiting() : reset()">{{ busy ? '取消等待' : '移除图片' }}</button></div>
      <p v-if="busy">取消等待不保证撤销上游已经开始的调用。</p>
    </template>
    <template v-if="draft">
      <p v-if="!file">已保留识别文字，图片未保留；可继续核对文字或重新选择图片。</p>
      <textarea v-model="draft" rows="5" maxlength="4000" aria-label="识别结果，确认前可修改" :disabled="busy || disabled" />
      <details class="transcription-preview">
        <summary>预览文字与公式</summary>
        <label><input v-model="codePreview" type="checkbox" />按代码预览，保留缩进</label>
        <pre v-if="codePreview" class="code-preview">{{ draft }}</pre>
        <MarkdownContent v-else :text="draft" />
      </details>
      <label v-if="hasText"><input v-model="replace" type="checkbox" />用已核对的识别结果替换下方现有过程</label>
      <button type="button" :disabled="busy || checking || disabled || !draft.trim() || (hasText && !replace)" @click="apply">确认并填入过程</button>
      <button v-if="!file" type="button" :disabled="disabled" @click="reset()">清除识别草稿</button>
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
.photo-review { width: min(1100px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); box-sizing: border-box; padding: 16px; border: 1px solid #e4e7eb; border-radius: 16px; background: white; color: var(--text-secondary); }
.photo-review::backdrop { background: rgb(20 30 45 / 30%); }
.photo-review-toolbar, .photo-zoom { display: flex; align-items: center; gap: 8px; }
.photo-review-toolbar { justify-content: space-between; flex-wrap: wrap; margin-bottom: 12px; }
.photo-review-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.photo-review-image { overflow: auto; max-height: min(65dvh, 560px); border-radius: 10px; min-width: 0; }
.review-original { max-width: none; max-height: none; margin: 0; border-radius: 0; height: auto; }
.photo-review-layout textarea { margin: 0; min-height: 180px; height: min(65dvh, 560px); padding: 12px; font: inherit; line-height: 1.7; }
@media (max-width: 650px) {
  .photo-review-layout { grid-template-columns: minmax(0, 1fr); }
  .photo-review-image { max-height: 35dvh; }
  .photo-review-layout textarea { height: 25dvh; min-height: 120px; }
}
</style>
