<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError } from "../api/client";
import { fetchChatMessages, streamChatAnswer, type ChatMessage, type Citation } from "../api/chat";
import { getDailyMaterialSearch, setMaterialSearchScope, type MaterialSearchSession } from "../api/materialSearch";
import { getMaterial, listMaterials, type Material } from "../api/materials";
import MarkdownContent from "./MarkdownContent.vue";
import { materialStatusLabel } from "../lib/labels";

const props = defineProps<{ revision?: number; initialScope?: string[] }>();
const emit = defineEmits<{ openSource: [id: string, chunkId: string]; upload: []; scopeChanged: [] }>();
const session = ref<MaterialSearchSession | null>(null);
const messages = ref<ChatMessage[]>([]);
const question = ref("");
const busy = ref(false);
const loading = ref(false);
const error = ref("");
const files = ref<Material[]>([]);
const scopeOpen = ref(false);
const scopeLoading = ref(false);
const scopeDraft = ref<string[]>([]);
const deletedSources = ref(new Set<string>());
const results = ref<HTMLElement | null>(null);
const input = ref<HTMLTextAreaElement | null>(null);
let controller: AbortController | null = null;
let mounted = true;
let initialScopeConsumed = false;
const scopeLabel = computed(() => session.value?.scope_mode === "selected" ? `已限定 ${session.value.selected_file_ids.length} 份资料` : "全部资料");
const canSend = computed(() => question.value.trim().length > 0 && !busy.value && !loading.value && Boolean(session.value));

async function syncDay(restore = false) {
  const current = await getDailyMaterialSearch();
  if (!mounted) return;
  const changed = current.session_id !== session.value?.session_id;
  session.value = current;
  if (changed || restore) messages.value = await fetchChatMessages(current.session_id);
  scopeDraft.value = [...current.selected_file_ids];
}

async function initialize() {
  loading.value = true; error.value = "";
  try {
    await syncDay(true);
    if (!initialScopeConsumed && props.initialScope?.length && session.value) {
      initialScopeConsumed = true;
      session.value = await setMaterialSearchScope(session.value.session_id, props.initialScope);
      emit("scopeChanged");
    }
  } catch (e) { error.value = e instanceof Error ? e.message : "资料搜索暂时无法加载"; }
  finally { loading.value = false; }
}

async function loadScopeFiles() {
  scopeLoading.value = true;
  try {
    const collected: Material[] = [];
    for (let offset = 0; ; offset += 100) {
      const batch = await listMaterials(100, offset, "", "user");
      collected.push(...batch.items);
      if (offset + batch.items.length >= batch.total || !batch.items.length) break;
    }
    files.value = collected;
  } catch (e) { error.value = e instanceof Error ? e.message : "无法读取资料范围"; }
  finally { scopeLoading.value = false; }
}

async function toggleScope() {
  if (busy.value || loading.value) return;
  scopeOpen.value = !scopeOpen.value;
  if (scopeOpen.value) {
    scopeDraft.value = [...(session.value?.selected_file_ids ?? [])];
    await loadScopeFiles();
  }
}

async function applyScope(ids = scopeDraft.value) {
  if (busy.value || loading.value) return;
  loading.value = true; error.value = "";
  try {
    await syncDay();
    if (session.value) session.value = await setMaterialSearchScope(session.value.session_id, ids);
    emit("scopeChanged");
    scopeOpen.value = false;
  } catch (e) { error.value = e instanceof Error ? e.message : "无法更新资料范围"; }
  finally { loading.value = false; }
}

async function useFile(id: string) {
  await applyScope([id]);
  input.value?.focus();
  input.value?.scrollIntoView({ block: "center", behavior: "smooth" });
}
defineExpose({ useFile, busy, loading });

async function refreshAfterFilesChanged() {
  if (busy.value || !session.value) return;
  if (scopeOpen.value) await loadScopeFiles();
  const selected = session.value.selected_file_ids;
  const valid: string[] = [];
  for (const id of selected) {
    try { const file = await getMaterial(id); if (file.status === "ready" && file.active_index_version) valid.push(id); }
    catch (e) { if (!(e instanceof ApiError && e.status === 404)) return; }
  }
  if (valid.length !== selected.length) await applyScope(valid);
  // Deleted citation rows are omitted by the backend; retain the answer text.
  if (mounted && session.value) messages.value = await fetchChatMessages(session.value.session_id);
}

async function openCitation(citation: Citation) {
  try { await getMaterial(citation.material_id); emit("openSource", citation.material_id, citation.chunk_id); }
  catch (e) {
    if (e instanceof ApiError && e.status === 404) deletedSources.value = new Set([...deletedSources.value, citation.material_id]);
    else error.value = e instanceof Error ? e.message : "无法打开来源";
  }
}

async function send() {
  if (!canSend.value) return;
  const text = question.value.trim(); busy.value = true; error.value = "";
  let reply: ChatMessage | null = null;
  let done = false;
  try {
    await syncDay();
    if (!session.value) return;
    question.value = "";
    messages.value.push({ message_id: crypto.randomUUID(), role: "user", content: text, status: "completed", citations: [], matched_kp_id: null });
    reply = { message_id: crypto.randomUUID(), role: "assistant", content: "", status: "generating", citations: [], matched_kp_id: null };
    messages.value.push(reply);
    // Use the reactive list entry so streamed updates reach the rendered result.
    reply = messages.value[messages.value.length - 1] ?? reply;
    controller = new AbortController();
    await streamChatAnswer(session.value.session_id, text, (event, data) => {
      if (!reply) return;
      if (event === "meta" && typeof data.message_id === "string") reply.message_id = data.message_id;
      if (event === "delta") reply.content = data.replace ? String(data.text ?? "") : reply.content + String(data.text ?? "");
      if (event === "citations") reply.citations = (data.citations ?? []) as Citation[];
      if (event === "done") {
        reply.content = String(data.answer ?? reply.content); reply.citations = (data.citations ?? reply.citations) as Citation[];
        reply.status = "completed"; reply.response_duration_ms = data.response_duration_ms as number | null; done = true;
      }
      if (event === "error") { reply.status = "failed"; error.value = String(data.message ?? "资料搜索未完成"); }
      void nextTick(() => results.value?.scrollTo({ top: results.value.scrollHeight }));
    }, controller.signal);
    if (!done && !error.value) error.value = "回答尚未完成，请刷新当天记录后重试。";
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") { if (reply) reply.status = "cancelled"; }
    else { error.value = e instanceof Error ? e.message : "资料搜索失败"; if (reply) reply.status = "failed"; }
  } finally {
    if (reply?.status === "generating") reply.status = "failed";
    busy.value = false; controller = null;
  }
}

function onEnter(event: KeyboardEvent) {
  if (event.isComposing || event.shiftKey) return;
  event.preventDefault(); void send();
}
function onVisible() { if (document.visibilityState === "visible" && !busy.value) void initialize(); }
watch(() => props.revision, () => { void refreshAfterFilesChanged().catch(e => { error.value = e instanceof Error ? e.message : "无法刷新资料搜索"; }); });
onMounted(() => { void initialize(); document.addEventListener("visibilitychange", onVisible); });
onBeforeUnmount(() => { mounted = false; controller?.abort(); document.removeEventListener("visibilitychange", onVisible); });
</script>

<template>
  <section class="material-search" aria-label="我的资料搜索" data-testid="material-search-panel">
    <header class="search-heading"><div><h2>搜索我的资料</h2><p>从你的笔记与文件中查找答案</p></div><span>当天记录保留，跨日自动删除</span></header>
    <form class="search-composer" @submit.prevent="send">
      <textarea ref="input" v-model="question" rows="2" maxlength="4000" placeholder="搜索我的资料，或继续追问…" aria-label="搜索我的资料" data-testid="material-search-question" @keydown.enter="onEnter" />
      <div class="composer-bottom">
        <button type="button" class="scope-toggle" :disabled="busy || loading" :aria-expanded="scopeOpen" data-testid="material-search-scope" @click="toggleScope">范围：{{ scopeLabel }} <span aria-hidden="true">⌄</span></button>
        <button v-if="busy" type="button" @click="controller?.abort()">停止</button>
        <button v-else type="submit" class="search-send" :disabled="!canSend" data-testid="material-search-send">发送</button>
      </div>
    </form>
    <div v-if="scopeOpen" class="scope-picker" data-testid="material-search-scope-picker">
      <button type="button" @click="applyScope([])">全部资料</button>
      <p v-if="scopeLoading" role="status">正在读取资料…</p>
      <div class="scope-files"><label v-for="file in files" :key="file.id"><input v-model="scopeDraft" type="checkbox" :value="file.id" :disabled="file.status !== 'ready' || !file.active_index_version || (scopeDraft.length >= 8 && !scopeDraft.includes(file.id))" /><span>{{ file.title }}</span><small>{{ file.status === 'ready' && file.active_index_version ? '可搜索' : materialStatusLabel(file.status) }}</small></label></div>
      <div class="scope-footer"><small>最多限定 8 份；清空后恢复全部资料</small><button type="button" :disabled="scopeLoading || loading" @click="applyScope([...scopeDraft])">应用范围</button></div>
    </div>
    <p v-if="loading" role="status">正在恢复当天记录…</p>
    <p v-if="error" class="search-error" role="alert" data-testid="material-search-error">{{ error }} <button v-if="!busy" type="button" @click="initialize">刷新记录</button></p>
    <div v-if="messages.length" ref="results" class="search-results" aria-live="polite" data-testid="material-search-results">
      <article v-for="message in messages" :key="message.message_id" :class="['search-result', `search-result--${message.role}`]" :data-testid="`material-search-${message.role}`">
        <p v-if="message.role === 'user'" class="search-query">{{ message.content }}</p>
        <template v-else>
          <p v-if="message.status === 'generating' && !message.content" role="status">正在搜索资料并整理答案…</p>
          <MarkdownContent v-if="message.content" :text="message.content" />
          <details v-if="message.citations.length" class="search-sources"><summary>依据 {{ new Set(message.citations.map(c => c.material_id)).size }} 份资料</summary><button v-for="citation in message.citations" :key="citation.label" type="button" :disabled="deletedSources.has(citation.material_id)" @click="openCitation(citation)">{{ deletedSources.has(citation.material_id) ? '来源已删除' : `[${citation.label}] ${citation.material_title}${citation.heading_path.length ? ' · ' + citation.heading_path.join(' / ') : ''}` }}</button></details>
          <p v-else-if="message.status === 'completed' && /\[C\d+\]/.test(message.content)" class="source-note">来源已删除或不再可定位</p>
          <p v-if="message.content.includes('还没有可检索的个人资料')" class="upload-hint"><button type="button" @click="emit('upload')">添加资料</button></p>
          <small v-if="message.status === 'cancelled'">已停止</small>
          <small v-else-if="message.status === 'failed'">本次搜索未完成</small>
        </template>
      </article>
    </div>
  </section>
</template>

<style scoped>
.material-search { margin-bottom: 30px; }
.search-heading { display:flex; justify-content:space-between; align-items:center; gap:18px; margin-bottom:14px; }
.search-heading h2 { font-size:20px; font-weight:600; margin:0; }
.search-heading p { color:var(--text-secondary); font-size:13px; margin:5px 0 0; }
.search-heading > span { color:var(--text-tertiary); font-size:11px; }
.search-composer { border:1px solid var(--border); border-radius:16px; background:#fff; padding:13px 16px 10px; }
.search-composer:focus-within { border-color:#adb8c6; }
.search-composer textarea { width:100%; display:block; min-height:58px; max-height:140px; resize:vertical; padding:0; border:0; outline:0; background:transparent; font:inherit; line-height:1.6; box-shadow:none; }
.composer-bottom { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-top:9px; }
.scope-toggle { border:0; background:transparent; padding:4px 0; color:var(--text-secondary); font-size:12px; }
.search-send { padding:5px 18px; border-radius:9px; background:#25272b; border:1px solid #25272b; color:#fff; }
.search-send:disabled { opacity:.4; }
.scope-picker { margin-top:9px; padding:12px 14px; border:1px solid var(--border); border-radius:13px; background:#fff; }
.scope-files { max-height:200px; overflow-y:auto; margin:8px 0; }
.scope-files label { display:flex; align-items:center; gap:9px; padding:7px 0; font-size:13px; }
.scope-files input { width:auto; }
.scope-files span { flex:1; min-width:0; overflow-wrap:anywhere; }
.scope-files small,.scope-footer small { color:var(--text-tertiary); font-size:11px; }
.scope-footer { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.search-results { margin-top:20px; max-height:460px; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; padding-right:8px; }
.search-result { margin:0 0 18px; }
.search-query { margin:0; font-size:14px; font-weight:600; color:var(--text); padding:9px 0; }
.search-result--assistant { font-size:14px; line-height:1.75; }
.search-sources { margin-top:10px; font-size:12px; color:var(--text-secondary); }
.search-sources summary { cursor:pointer; }
.search-sources button { display:block; text-align:left; border:0; background:transparent; padding:5px 0; max-width:100%; overflow-wrap:anywhere; }
.search-error { color:var(--danger); font-size:13px; }
.source-note { font-size:12px; color:var(--text-tertiary); }
.upload-hint { margin:8px 0; }
@media(max-width:600px) { .search-heading > span { max-width:110px; text-align:right; }.search-heading h2 { font-size:18px; }.scope-footer { flex-wrap:wrap; }.search-results { max-height:400px; } }
</style>
