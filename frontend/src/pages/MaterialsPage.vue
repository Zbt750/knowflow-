<script setup lang="ts">
// 资料页：以列表阅读为主，上传与索引管理为次要操作。
//
// 职责边界（见设计文档「资料页」一节）：本页只负责「把资料变成可检索」——
// 上传、进度、失败原因、重试、删除，以及 READY 后**限定这份资料进入问答**。
// 检索与问答属于 /chat 页面，不在这里重复实现。
// 约束：所有业务状态（状态、块数、索引版本、块内容、检索结果）都来自后端；
// 页面只负责展示与触发动作，不自己推断资料"是不是可用"。

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import MarkdownContent from "../components/MarkdownContent.vue";
import {
  deleteMaterial,
  getMaterial,
  getMaterialContent,
  listChunks,
  listMaterials,
  reindexMaterial,
  retryMaterial,
  uploadMaterial,
  type ChunkPreview,
  type MaterialDetail,
  type MaterialContentResponse,
  type MaterialListResponse,
  type UploadResponse,
} from "../api/materials";
import { StaleResponse, useAsyncTask } from "../composables/useAsyncTask";
import {
  MAX_FILE_MB,
  formatBytes,
  formatTime,
  headingPathLabel,
  jobStatusLabel,
  materialErrorLabel,
  materialStatusClass,
  materialStatusLabel,
} from "../lib/labels";

const SUPPORTED_SUFFIXES = [".md", ".txt", ".docx", ".pdf"];
const POLL_INTERVAL_MS = 1500;

const list = useAsyncTask<MaterialListResponse>();
const detail = useAsyncTask<MaterialDetail>();
const chunkList = useAsyncTask<{ items: ChunkPreview[]; total: number }>();
// 上传是独立任务：它的返回值类型与列表不同，混用会让类型系统无法表达。
const upload = useAsyncTask<UploadResponse>();
const contentTask = useAsyncTask<MaterialContentResponse>();

const selectedId = ref<string | null>(null);
const uploadTitle = ref("");
const selectedFile = ref<File | null>(null);
const showDetail = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const uploadNotice = ref<string | null>(null);
const actionNotice = ref<string | null>(null);
const actionError = ref<string | null>(null);
/**
 * 详情是否展开。
 *
 * 默认收起：列表只用于浏览，具体索引与分块由用户主动展开。
 * 但资料多、块预览长时，列表浏览体验会被拖得很长，所以提供整体收起，
 * 从问答引用跳到指定分块时自动展开并定位。
 */
const detailExpanded = ref(false);
const route = useRoute();
const router = useRouter();
const focusedChunkId = ref<string | null>(null);

let pollTimer: number | null = null;
let uploadController: AbortController | null = null;


const materials = computed(() => list.data.value?.items ?? []);
const stats = computed(() => list.data.value?.stats ?? {});
const PAGE_SIZE = 8;
const currentPage = ref(1);
const searchInput = ref("");
const searchQuery = ref("");
let searchTimer: number | null = null;
let listRequestToken = 0;
const pageCount = computed(() => Math.max(1, Math.ceil((list.data.value?.total ?? 0) / PAGE_SIZE)));
const pageNumbers = computed(() => {
  const start = Math.max(1, Math.min(currentPage.value - 2, pageCount.value - 4));
  return Array.from({ length: Math.min(5, pageCount.value) }, (_, index) => start + index);
});
const entryRange = computed(() => {
  const total = list.data.value?.total ?? 0;
  if (!total) return "暂无资料";
  const first = (currentPage.value - 1) * PAGE_SIZE + 1;
  return `${first}–${Math.min(first + materials.value.length - 1, total)} / ${total} 份`;
});
const visibleMaterials = materials;
/** 有资料正在处理时才需要轮询，避免空转请求。 */
const hasPending = computed(() =>
  materials.value.some((item) => item.status === "pending" || item.status === "indexing"),
);
const selected = computed(() => detail.data.value);
const isBusy = computed(
  () => list.submitting.value || detail.submitting.value || upload.submitting.value,
);

/** 统一的错误文案：错误码转中文，并保留原始码便于定位。 */
function errorText(code: string | null, message?: string | null): string {
  if (!code) return message || "请求失败";
  return `${materialErrorLabel(code)}（${code}）`;
}

async function loadList(preserveSelection = true): Promise<void> {
  const token = ++listRequestToken;
  const page = currentPage.value;
  const query = searchQuery.value;
  const result = await list.run(async () => {
    const response = await listMaterials(PAGE_SIZE, (page - 1) * PAGE_SIZE, query);
    if (token !== listRequestToken) throw new StaleResponse();
    return response;
  });
  if (token !== listRequestToken) return;
  if (!result) return;
  // 搜索请求也会改变当前页内的处理状态；不要只在初次挂载时启动轮询。
  syncPolling();
  if (!result.items.length && result.total > 0 && currentPage.value > 1) {
    currentPage.value = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
    await loadList(false);
    return;
  }
  if (query && !showDetail.value) {
    selectedId.value = null;
    detail.reset();
    chunkList.reset();
    if (route.query.material_id) {
      await router.replace({ path: route.path, query: { ...route.query, material_id: undefined, chunk_id: undefined } });
    }
    return;
  }
  const stillThere = result.items.some((item) => item.id === selectedId.value);
  if (!preserveSelection || !stillThere) {
    const first = result.items[0];
    if (first) {
      // restoreHistory=true：这是页面自动代入的选中，不是用户点的，
      // 不能因此压一条历史（否则每次进入本页都会多出一条）。
      await selectMaterial(first.id, undefined, true);
    } else {
      selectedId.value = null;
      detail.reset();
      chunkList.reset();
    }
  }
}

async function selectMaterial(id: string, focusChunkId?: string, restoreHistory = false): Promise<void> {
  selectedId.value = id;
  detailExpanded.value = false;
  actionNotice.value = null;
  actionError.value = null;
  await detail.run(() => getMaterial(id));
  await chunkList.run(() => listChunks(id, 20, focusChunkId));
  await syncUrlQuery(id, focusChunkId ?? null, restoreHistory);
  focusedChunkId.value = focusChunkId ?? null;
  if (focusChunkId) {
    detailExpanded.value = true;
    await nextTick();
    document.getElementById(`chunk-${focusChunkId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

async function openMaterial(id: string, focusChunkId?: string, restoreHistory = false): Promise<void> {
  showDetail.value = true;
  contentTask.reset();
  await selectMaterial(id, focusChunkId, restoreHistory);
  await contentTask.run(() => getMaterialContent(id));
}

function closeDetail(): void { showDetail.value = false; }
function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && showDetail.value) closeDetail();
}

/**
 * 把当前选择同步进 URL query。
 *
 * 用 push（不是 replace）：点击资料是一次**用户导航**，
 * 应该产生一条历史记录，这样「后退」才回到上一份资料或列表，
 * 而不是把用户直接弹出这一页。实测踩过：用 replace 时后退会跳过列表，
 * 因为历史里根本没有「列表」那条状态（它被原地改写了）。
 */
async function syncUrlQuery(materialId: string, chunkId: string | null, restore: boolean): Promise<void> {
  const query: Record<string, string> = { ...(route.query as Record<string, string>), material_id: materialId };
  if (chunkId) query.chunk_id = chunkId;
  else delete query.chunk_id;
  const currentMaterial = typeof route.query.material_id === "string" ? route.query.material_id : null;
  const currentChunk = typeof route.query.chunk_id === "string" ? route.query.chunk_id : null;
  const targetChunk = chunkId ?? null;
  // 已经是同一个状态就不要再动历史（例如同一份资料被重复选中）。
  if (currentMaterial === materialId && currentChunk === targetChunk) return;
  const target = { path: route.path, query };
  if (restore) {
    // restore=true：这次选中是「页面自己恢复出来的」（打开页面时代入 URL 里的选择、
    // 或自动选中列表第一份），不是用户点出来的，所以**不产生新的历史条目**。
    // 但 URL 仍要写成当前真实状态，否则用户看不出自己在看哪一份、也无法分享链接。
    //
    // 这里必须用 replace 而不是「什么都不做」：实测每次进入 /materials 时
    // loadList() 会自动选中第一份资料，那次 push 会让一次访问在同一页留下
    // 两条历史（history.length 从 3 直接跳到 5），用户按后退先退到「同一页的
    // 无参状态」，看起来就是后退失灵。replace 只改写当前条目，不新增。
    await router.replace(target);
    return;
  }
  // 用户点击资料：这是一次真实导航，压一条历史，让后退能回到上一份/列表。
  await router.push(target);
}

async function goToPage(page: number): Promise<void> {
  if (isBusy.value || page < 1 || page > pageCount.value || page === currentPage.value) return;
  currentPage.value = page;
  showDetail.value = false;
  await loadList(false);
}

function syncPolling(): void {
  if (hasPending.value && pollTimer === null) {
    pollTimer = window.setInterval(() => {
      void refreshQuietly();
    }, POLL_INTERVAL_MS);
    return;
  }
  if (!hasPending.value && pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

/** 轮询刷新：只更新列表与当前详情，不打断用户的选中状态与输入。 */
async function refreshQuietly(): Promise<void> {
  const token = ++listRequestToken;
  const page = currentPage.value;
  const query = searchQuery.value;
  const result = await list.run(async () => {
    const response = await listMaterials(PAGE_SIZE, (page - 1) * PAGE_SIZE, query);
    if (token !== listRequestToken) throw new StaleResponse();
    return response;
  }, { keepPreviousData: true });
  if (token !== listRequestToken) return;
  const current = selectedId.value;
  if (result && current) {
    // 先取出到局部变量，Promise 回调里才能安全使用（此时可能已被改成 null）。
    const material = await detail.run(() => getMaterial(current), { keepPreviousData: true });
    // ready 但块列表还是空，说明刚刚处理完（或块列表请求还没跟上）—— 补一次请求。
    // 判据用「块列表是否已有内容」而不是「状态是否刚变化」：
    // 后者需要额外记录上次状态，容易在 selectMaterial 等路径上漏记而失效。
    const chunkTotal = chunkList.data.value?.total ?? 0;
    if (material && material.status === "ready" && chunkTotal === 0) {
      await chunkList.run(() => listChunks(current, 20));
    }
    if (showDetail.value && material?.status === "ready" && !contentTask.data.value?.text) {
      await contentTask.run(() => getMaterialContent(current));
    }
  }
  syncPolling();
}

function cancelUpload(): void {
  const wasUploading = upload.submitting.value;
  uploadController?.abort();
  uploadController = null;
  if (wasUploading) {
    // 取消浏览器到服务端的上传请求；如果服务端已完整收到并提交，任务仍可能继续。
    upload.reset();
    uploadNotice.value = "已取消上传请求。若文件已完整送达服务端，资料仍可能进入列表。";
  }
  selectedFile.value = null;
  uploadTitle.value = "";
  actionError.value = null;
  if (fileInput.value) fileInput.value.value = "";
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
  uploadNotice.value = null;
  // 标题留空时用文件名兜底，减少一次手动输入。
  if (selectedFile.value && !uploadTitle.value.trim()) {
    uploadTitle.value = selectedFile.value.name.replace(/\.[^.]+$/, "");
  }
}

async function submitUpload(): Promise<void> {
  uploadNotice.value = null;
  actionError.value = null;
  const file = selectedFile.value;
  if (!file) {
    actionError.value = "请先选择要上传的文件";
    return;
  }
  const lower = file.name.toLowerCase();
  if (!SUPPORTED_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    // 后端也会校验，这里先拦一次，省掉一次无意义的往返。
    actionError.value = `只支持 ${SUPPORTED_SUFFIXES.join("、")} 四种格式`;
    return;
  }
  if (!uploadTitle.value.trim()) {
    actionError.value = "请填写资料标题";
    return;
  }
  // 前端先拦一次，让用户**在上传前**就知道结果，而不是传完再异步失败。
  // 上限与后端 MAX_FILE_BYTES 是同一个值，因此不存在「传上去才失败」的中间地带。
  if (file.size > MAX_FILE_MB * 1024 * 1024) {
    actionError.value =
      `文件为 ${formatBytes(file.size)}，超过 ${MAX_FILE_MB} MB 上限。` +
      "请拆分文件，或先用 Markdown/TXT 粘贴需要的章节。";
    return;
  }

  const controller = new AbortController();
  uploadController = controller;
  const created = await upload.submit(() =>
    uploadMaterial(file, uploadTitle.value.trim(), "user", controller.signal),
  );
  if (uploadController === controller) uploadController = null;
  if (!created) {
    if (controller.signal.aborted) return;
    actionError.value = errorText(upload.errorCode.value, upload.errorMessage.value);
    return;
  }
  uploadNotice.value = created.message;
  showDetail.value = false;
  selectedFile.value = null;
  uploadTitle.value = "";
  if (fileInput.value) fileInput.value.value = "";
  // 新资料排在首页，列表直接显示状态；阅读器由用户主动打开。
  currentPage.value = 1;
  await loadList(false);
  syncPolling();
}

/** 触发一个针对当前资料的动作（重建/重试），动作后刷新状态。 */
async function runAction(label: string, action: (id: string) => Promise<unknown>): Promise<void> {
  const id = selectedId.value;
  if (!id) return;
  actionNotice.value = null;
  actionError.value = null;
  const submitted = await detail.submit(async () => {
    await action(id);
    return (await getMaterial(id)) as MaterialDetail;
  });
  if (!submitted) {
    actionError.value = errorText(detail.errorCode.value, detail.errorMessage.value);
    return;
  }
  actionNotice.value = `${label}已提交，状态会自动刷新`;
  await refreshQuietly();
}

function removeMaterial(): void {
  const id = selectedId.value;
  const material = selected.value;
  if (!id || !material) return;
  // 删除是不可逆动作，必须显式确认。
  if (!window.confirm(`确定删除《${material.title}》吗？正文、索引与磁盘文件都会被清理。`)) return;
  actionNotice.value = null;
  actionError.value = null;
  void (async () => {
    const deleted = await detail.submit(async () => {
      await deleteMaterial(id);
      return material;
    });
    if (!deleted) {
      actionError.value = errorText(detail.errorCode.value, detail.errorMessage.value);
      return;
    }
    selectedId.value = null;
    showDetail.value = false;
    detail.reset();
    chunkList.reset();
    await loadList(false);
    actionNotice.value = "资料已删除";
    syncPolling();
  })();
}

watch(searchInput, (value) => {
  if (searchTimer !== null) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    searchTimer = null;
    const next = value.trim();
    if (next === searchQuery.value) return;
    searchQuery.value = next;
    currentPage.value = 1;
    showDetail.value = false;
    void loadList(false);
  }, 250);
});

watch(
  () => [route.query.material_id, route.query.chunk_id],
  ([materialId, chunkId]) => {
    const id = typeof materialId === "string" ? materialId : null;
    const focusId = typeof chunkId === "string" ? chunkId : undefined;
    if (id && (id !== selectedId.value || focusId !== (focusedChunkId.value ?? undefined))) {
      void openMaterial(id, focusId, true);
    } else if (!id) {
      showDetail.value = false;
    }
  },
);
onMounted(async () => {
  window.addEventListener("keydown", handleKeydown);
  const requestedId = typeof route.query.material_id === "string" ? route.query.material_id : null;
  const chunkId = typeof route.query.chunk_id === "string" ? route.query.chunk_id : undefined;
  await loadList(false);
  if (requestedId) await openMaterial(requestedId, chunkId, true);
  syncPolling();
});

onBeforeUnmount(() => {
  uploadController?.abort();
  uploadController = null;
  window.removeEventListener("keydown", handleKeydown);
  if (pollTimer !== null) window.clearInterval(pollTimer);
  pollTimer = null;
  if (searchTimer !== null) window.clearTimeout(searchTimer);
});
</script>

<template>
  <section class="page materials-page" data-testid="materials-page">
    <header class="materials-header">
      <div><p>选择资料，直接阅读正文。</p></div>
      <div class="materials-header-actions">
        <button type="button" class="refresh-button" :disabled="isBusy" @click="loadList(true)">刷新</button>
        <button type="button" class="upload-toggle" data-testid="upload-toggle" @click="fileInput?.click()">添加资料</button>
      </div>
    </header>

    <input ref="fileInput" class="upload-file-input" type="file" :accept="SUPPORTED_SUFFIXES.join(',')" aria-label="选择本地资料文件" tabindex="-1" data-testid="upload-file" @change="onFileChange" />
    <p v-if="list.state.value === 'loading' && !materials.length" class="state state--loading">正在加载资料…</p>
    <div v-if="list.state.value === 'error'" class="state state--error" data-testid="materials-error">
      <p>{{ errorText(list.errorCode.value, list.errorMessage.value) }}</p>
      <button type="button" @click="loadList(false)">重试</button>
    </div>

    <form v-if="selectedFile" class="upload-panel" data-testid="upload-form" @submit.prevent="submitUpload">
      <div class="upload-selection"><strong>{{ selectedFile.name }}</strong><span>{{ formatBytes(selectedFile.size) }}</span></div>
      <label class="field field--title"><span>资料标题</span><input v-model="uploadTitle" type="text" maxlength="200" placeholder="资料标题" data-testid="upload-title" /></label>
      <button type="submit" class="primary upload-submit" :disabled="isBusy" data-testid="upload-submit">{{ upload.submitting.value ? "上传中…" : "确认上传" }}</button>
      <button type="button" class="upload-cancel" data-testid="upload-cancel" @click="cancelUpload">{{ upload.submitting.value ? "取消上传" : "取消" }}</button>
      <p v-if="actionError" class="form-error" data-testid="action-error">{{ actionError }}</p>
    </form>
    <p v-if="uploadNotice && !selectedFile" class="notice upload-brief-notice" data-testid="upload-notice">{{ uploadNotice }}</p>
    <p v-if="actionNotice && !showDetail" class="notice" data-testid="action-notice">{{ actionNotice }}</p>
    <p v-if="actionError && !selectedFile" class="form-error" data-testid="action-error">{{ actionError }}</p>

    <div class="stats-row" data-testid="materials-stats">
      <span><strong>共 {{ stats.total ?? 0 }} 份</strong></span>
      <span><strong>{{ stats.ready ?? 0 }}</strong><small>可检索</small></span>
      <span v-if="(stats.failed ?? 0) > 0" class="stat-error"><strong>{{ stats.failed }}</strong><small>失败</small></span>
    </div>

    <div class="materials-layout">
      <section class="list-panel">
        <header class="panel-head materials-list-head"><div><h2>资料</h2><span>{{ searchQuery ? `匹配 ${list.data.value?.total ?? 0} 份` : `${list.data.value?.total ?? 0} 份` }}</span></div><input v-model="searchInput" type="search" maxlength="120" aria-label="搜索资料名称" placeholder="搜索资料名称" data-testid="material-search" /></header>
        <p v-if="list.state.value === 'success' && !materials.length" class="state state--empty" data-testid="materials-empty">{{ searchQuery ? "没有找到匹配的资料，试试其他名称。" : "还没有资料，点击右上角“添加资料”选择文件。" }}</p>
        <ul v-else class="material-list" data-testid="material-list">
          <li v-for="item in visibleMaterials" :key="item.id">
            <div class="material-item" :class="{ 'material-item--selected': item.id === selectedId && showDetail }">
              <span class="file-glyph" aria-hidden="true"></span>
              <span class="material-item__main">
                <span class="material-item__title">{{ item.title }}</span>
                <span class="material-item__sub">{{ item.source_type === "builtin" ? "系统资料" : "我的资料" }}<template v-if="item.original_filename"> · {{ item.original_filename }}</template></span>
                <span v-if="item.last_error_code" class="material-item__error">{{ materialErrorLabel(item.last_error_code) }}</span>
              </span>
              <span class="material-status" :class="materialStatusClass(item.status)">{{ materialStatusLabel(item.status) }}</span>
              <button type="button" class="material-view" :aria-label="'查看' + item.title" @click="openMaterial(item.id)">阅读 <span aria-hidden="true">→</span></button>
            </div>
          </li>
        </ul>
        <nav v-if="list.state.value === 'success'" class="materials-pagination" aria-label="资料分页" data-testid="materials-pagination">
          <span class="materials-entry-range">{{ entryRange }}</span>
          <div class="materials-page-buttons">
            <button type="button" :disabled="isBusy || currentPage === 1" @click="goToPage(currentPage - 1)">上一页</button>
            <button v-if="pageNumbers[0] > 1" type="button" aria-label="第 1 页" :disabled="isBusy" @click="goToPage(1)">1</button>
            <span v-if="pageNumbers[0] > 2" aria-hidden="true">…</span>
            <button v-for="page in pageNumbers" :key="page" type="button" :aria-label="`第 ${page} 页`" :aria-current="page === currentPage ? 'page' : undefined" :disabled="isBusy" @click="goToPage(page)">{{ page }}</button>
            <span v-if="pageNumbers[pageNumbers.length - 1] < pageCount - 1" aria-hidden="true">…</span>
            <button v-if="pageNumbers[pageNumbers.length - 1] < pageCount" type="button" :aria-label="`第 ${pageCount} 页`" :disabled="isBusy" @click="goToPage(pageCount)">{{ pageCount }}</button>
            <button type="button" :disabled="isBusy || currentPage === pageCount" @click="goToPage(currentPage + 1)">下一页</button>
          </div>
          <span class="materials-page-status" aria-live="polite">第 {{ currentPage }} / {{ pageCount }} 页</span>
        </nav>
      </section>
    </div>

    <div v-if="showDetail" class="reader-backdrop" @click="closeDetail"></div>
    <aside v-if="showDetail" class="detail-panel" role="dialog" aria-modal="true" aria-label="资料阅读器">
      <p v-if="detail.state.value === 'loading' && (!selected || selected.id !== selectedId)" class="detail-empty">正在打开资料…</p>
      <p v-else-if="!selected || selected.id !== selectedId" class="detail-empty" data-testid="detail-empty">暂时无法读取这份资料。</p>
      <div v-else data-testid="material-detail">
        <header class="detail-head">
          <div><h2 data-testid="detail-title">{{ selected.title }}</h2><p>{{ selected.original_filename ?? "资料" }}</p></div>
          <button type="button" class="reader-close" aria-label="关闭资料" @click="closeDetail">关闭</button>
        </header>
        <div class="detail-summary">
          <span class="material-status" :class="materialStatusClass(selected.status)" data-testid="detail-status">{{ materialStatusLabel(selected.status) }}</span>
        </div>

        <section class="reader-body" data-testid="material-reader">
          <p v-if="contentTask.state.value === 'loading'" class="detail-empty">正在读取正文…</p>
          <p v-else-if="contentTask.state.value === 'error'" class="form-error">{{ contentTask.errorMessage.value }}</p>
          <MarkdownContent v-else-if="contentTask.data.value?.text" class="reader-text" :text="contentTask.data.value.text" />
          <p v-else class="detail-empty">正文尚未处理完成，请稍后刷新。</p>
        </section>

        <button type="button" class="collapse-toggle" :aria-expanded="detailExpanded" data-testid="detail-toggle" @click="detailExpanded = !detailExpanded">{{ detailExpanded ? "收起索引信息" : "查看索引信息" }}</button>
        <template v-if="detailExpanded">
          <dl class="facts">
            <div><dt>索引版本</dt><dd class="mono" data-testid="detail-index-version">{{ selected.active_index_version ?? "尚未建立" }}</dd></div>
            <div><dt>分块数</dt><dd data-testid="detail-chunk-count">{{ selected.chunk_count }}</dd></div>
            <div><dt>上传时间</dt><dd>{{ formatTime(selected.created_at) }}</dd></div>
            <div>
              <dt>最近任务</dt>
              <dd v-if="selected.latest_job" data-testid="detail-latest-job">{{ selected.latest_job.job_type }} · {{ jobStatusLabel(selected.latest_job.status) }} · {{ selected.latest_job.attempts }}/{{ selected.latest_job.max_attempts }}</dd>
              <dd v-else>—</dd>
            </div>
            <div v-if="selected.last_error_code"><dt>失败原因</dt><dd class="error-text" data-testid="detail-error-code">{{ materialErrorLabel(selected.last_error_code) }}</dd></div>
          </dl>
          <div class="actions detail-actions">
            <button type="button" :disabled="isBusy" data-testid="action-reindex" @click="runAction('重建索引', reindexMaterial)">重建索引</button>
            <button type="button" :disabled="isBusy || selected.status !== 'failed'" data-testid="action-retry" @click="runAction('重试处理', retryMaterial)">重试</button>
            <button type="button" class="danger" :disabled="isBusy" data-testid="action-delete" @click="removeMaterial">删除</button>
          </div>
          <p v-if="actionNotice" class="notice" data-testid="action-notice">{{ actionNotice }}</p>
          <div class="chunks-head"><h3>索引片段</h3><span>最多显示 20 条</span></div>
          <p v-if="!chunkList.data.value?.total" class="detail-empty">处理完成后可查看片段。</p>
          <ol v-else class="chunk-list" data-testid="chunk-list">
            <li v-for="chunk in chunkList.data.value.items" :id="'chunk-' + chunk.id" :key="chunk.id" :class="{ 'chunk-list__item--focused': chunk.id === focusedChunkId }">
              <div class="chunk-head">
                <span class="chunk-index">{{ chunk.ordinal + 1 }}</span><span class="chunk-path">{{ headingPathLabel(chunk.heading_path) }}</span><span class="chunk-count">{{ chunk.char_count }} 字</span>
                <span v-if="chunk.kp_hint_code" class="chunk-kp" data-testid="chunk-kp">{{ chunk.kp_hint_code }}</span>
              </div>
              <p class="chunk-preview">{{ chunk.preview }}</p>
            </li>
          </ol>
        </template>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.materials-page { width: min(1120px, 100%); }
.materials-header { display: flex; align-items: start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.materials-header p { margin: 3px 0 0; color: var(--text-secondary); }
.refresh-button { flex: 0 0 auto; }

.stats-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.stats-row > span { display: inline-flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.stats-row strong { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stats-row small { color: var(--text-secondary); font-size: 12px; }
.stats-row .stat-error strong, .stats-row .stat-error small { color: var(--danger); }

.upload-panel {
  margin-bottom: 24px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}
.upload-panel__head { margin-bottom: 14px; }
.upload-panel__head h2 { margin: 0; font-size: 14px; font-weight: 600; }
.upload-panel__head p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.upload-row { display: grid; grid-template-columns: minmax(160px, 1fr) 138px minmax(205px, 1.15fr) auto; align-items: end; gap: 10px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 5px; color: var(--text-secondary); font-size: 12px; }
.field input[type="text"], .field select { width: 100%; min-width: 0; min-height: 36px; padding: 6px 9px; }
.field input[type="file"] { width: 100%; min-height: 36px; padding: 5px 6px; color: var(--text-secondary); background: #fff; }
.field input[type="file"]::file-selector-button { margin-right: 8px; padding: 4px 8px; border: 0; border-radius: 4px; background: #ededed; font: inherit; cursor: pointer; }
.upload-submit { min-height: 36px; padding-inline: 17px; }
.upload-name { margin: 10px 0 0; color: var(--text-secondary); font-size: 12px; }

.materials-layout { display: grid; gap: 18px; }
.list-panel, .detail-panel { min-width: 0; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
.list-panel { overflow: hidden; }
.panel-head { display: flex; align-items: baseline; gap: 9px; padding: 15px 18px 13px; border-bottom: 1px solid var(--border); }
.panel-head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.panel-head span { color: var(--text-tertiary); font-size: 12px; }
.material-list-columns { display: flex; justify-content: space-between; padding: 7px 18px 7px 54px; border-bottom: 1px solid var(--border); color: var(--text-tertiary); font-size: 11px; }
.material-list { max-height: 355px; margin: 0; padding: 0; overflow-y: auto; list-style: none; scrollbar-width: thin; scrollbar-color: #c7c9cc transparent; }
.material-list li:not(:last-child) { border-bottom: 1px solid var(--border); }
.material-item {
  display: grid;
  grid-template-columns: 25px minmax(0, 1fr) 88px;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 57px;
  padding: 8px 18px;
  border: 0;
  border-radius: 0;
  background: #fff;
  text-align: left;
}
.material-item:hover:not(:disabled) { background: #f8f8f8; }
.material-item--selected, .material-item--selected:hover:not(:disabled) { background: #f1f3f4; }
.file-glyph { position: relative; display: block; width: 19px; height: 24px; border: 1px solid #aeb0b4; border-radius: 2px; background: #fff; }
.file-glyph::before { content: ""; position: absolute; top: 5px; left: 4px; width: 9px; height: 1px; background: #b7b9bc; box-shadow: 0 4px #b7b9bc, 0 8px #b7b9bc; }
.material-item__main { display: grid; min-width: 0; gap: 2px; }
.material-item__title { overflow: hidden; color: var(--text); font-size: 13px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.material-item__sub, .material-item__error { overflow: hidden; color: var(--text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.material-item__error { color: var(--danger); }
.material-status { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.material-status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #9da0a4; }
.material-status.tag--status-ready::before { background: #3e914e; }
.material-status.tag--status-indexing::before { background: #c28618; }
.material-status.tag--status-failed::before { background: #c33b32; }
.material-status.tag--status-ready { color: var(--success); }
.material-status.tag--status-indexing { color: var(--warning); }
.material-status.tag--status-failed { color: var(--danger); }

.detail-panel { min-height: 210px; padding: 18px; }
.detail-empty { margin: 0; padding: 24px 2px; color: var(--text-secondary); font-size: 13px; }
.detail-head { display: flex; align-items: start; justify-content: space-between; gap: 12px; padding-bottom: 13px; border-bottom: 1px solid var(--border); }
.detail-head h2 { margin: 0; font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.detail-head p { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
.collapse-toggle { flex: 0 0 auto; }
.detail-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 9px 20px; padding: 11px 0; border-bottom: 1px solid var(--border); color: var(--text-secondary); font-size: 12px; }
.facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 20px; margin: 0; border-bottom: 1px solid var(--border); }
.facts > div { min-width: 0; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.facts dt { margin-bottom: 3px; color: var(--text-tertiary); font-size: 11px; }
.facts dd { min-width: 0; margin: 0; color: var(--text); font-size: 12px; font-weight: 500; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.error-text { color: var(--danger) !important; }
.detail-actions { padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.detail-actions .danger { margin-left: auto; border-color: #e4c1bd; color: var(--danger); }
.detail-actions .danger:hover:not(:disabled) { background: #fff5f4; }

.chunks-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-top: 18px; }
.chunks-head h3 { margin: 0; font-size: 14px; font-weight: 600; }
.chunks-head span { color: var(--text-tertiary); font-size: 11px; }
.chunk-list { max-height: 460px; margin: 10px 0 0; padding: 0; overflow-y: auto; list-style: none; scrollbar-width: thin; }
.chunk-list li { padding: 13px 0; border-top: 1px solid var(--border); }
.chunk-list__item--focused { margin-inline: -8px; padding-inline: 8px !important; background: #fff8dc; outline: 1px solid #d4a72c; }
.chunk-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.chunk-index { display: grid; flex: 0 0 22px; width: 22px; height: 22px; place-items: center; border: 1px solid var(--border); border-radius: 4px; color: var(--text-tertiary); font-size: 11px; }
.chunk-path { overflow: hidden; flex: 1; color: var(--text-secondary); font-size: 12px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.chunk-count, .chunk-kp { color: var(--text-tertiary); font-size: 11px; white-space: nowrap; }
.chunk-kp { color: var(--info); }
.chunk-preview { margin: 7px 0 0 30px; color: var(--text-secondary); font-size: 12px; line-height: 1.7; }

@media (max-width: 950px) {
  .upload-row { grid-template-columns: minmax(0, 1fr) 140px; }
  .field--file { grid-column: 1 / -1; }
  .upload-submit { justify-self: start; }
  .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .materials-header { align-items: center; }
  .stats-row { gap: 7px 17px; }
  .upload-panel, .detail-panel { padding: 14px; }
  .upload-row { grid-template-columns: minmax(0, 1fr); }
  .field--file { grid-column: auto; }
  .upload-submit { width: 100%; }
  .material-list-columns { display: none; }
  .material-item { grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; padding-inline: 12px; }
  .facts { grid-template-columns: minmax(0, 1fr); }
  .detail-actions button { flex: 1; }
  .detail-actions .danger { margin-left: 0; }
}

/* 浏览优先，上传只在明确点击时出现。 */
.materials-header { margin-bottom: 12px; }
.materials-header-actions { display: flex; align-items: center; gap: 7px; }
.materials-header-actions .upload-toggle { border-color: #2d2e30; color: #fff; background: #2d2e30; }
.materials-header-actions .upload-toggle:hover:not(:disabled) { background: #161719; }
.upload-panel { margin-bottom: 18px; padding: 14px 16px; background: #fafafa; }
.upload-panel__head { margin-bottom: 10px; }
.upload-row { grid-template-columns: minmax(190px, 1.2fr) minmax(160px, 1fr) auto; }
.stats-row { margin-bottom: 12px; }
.materials-layout { gap: 14px; }
.list-panel, .detail-panel { border-radius: 0; border-inline: 0; }
.list-panel { border-top: 1px solid var(--border); }
.panel-head { padding-inline: 4px; }
.material-list-columns { padding-right: 4px; padding-left: 38px; }
.material-item { min-height: 47px; padding-inline: 4px; }
.material-item--selected, .material-item--selected:hover:not(:disabled) { background: #f6f6f6; }
.material-item__title { font-size: 13px; }
.detail-panel { min-height: 100px; padding: 16px 4px; }
.detail-summary { padding-bottom: 0; border-bottom: 0; }
.materials-pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 12px 0; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 12px; }
.materials-pagination button { min-height: 28px; padding: 3px 8px; border: 0; color: var(--text-secondary); background: transparent; }
.materials-pagination button:hover:not(:disabled) { background: #f2f2f2; }
.upload-brief-notice { margin: 0 0 12px; border: 0; background: transparent; }
@media (max-width: 950px) { .upload-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .upload-submit { grid-column: 1 / -1; } }
@media (max-width: 560px) { .materials-header-actions { gap: 3px; } .upload-row { grid-template-columns: minmax(0, 1fr); } .upload-submit { grid-column: auto; } .material-list-columns { display: none; } .material-item { padding-inline: 2px; } }

/* 资料列表是主界面；阅读全文与索引管理只在行末“查看”后出现。 */
.materials-page { width: min(1040px, 100%); }
.materials-header { margin-bottom: 14px; }
.upload-file-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.upload-panel {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(180px, 1fr) auto auto;
  align-items: end;
  gap: 10px;
  margin: 0 0 18px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #fafafa;
}
.upload-selection { display: grid; align-content: end; min-width: 0; min-height: 36px; gap: 1px; }
.upload-selection strong { overflow: hidden; font-size: 12px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.upload-selection span { color: var(--text-tertiary); font-size: 11px; }
.upload-panel .field { margin: 0; }
.upload-panel .form-error { grid-column: 1 / -1; margin: 0; }
.upload-panel .upload-submit, .upload-panel .upload-cancel { min-height: 36px; }
.stats-row { margin-bottom: 7px; }
.list-panel { border: 0; border-top: 1px solid var(--border); }
.material-list { max-height: none; }
.material-item { grid-template-columns: 24px minmax(0, 1fr) 78px 50px; min-height: 54px; gap: 10px; padding: 7px 4px; border: 0; }
.material-item--selected, .material-item--selected:hover:not(:disabled) { background: #fafafa; }
.material-view { min-height: 28px; padding: 3px 5px; border: 0; color: var(--text-secondary); background: transparent; font-size: 12px; font-weight: 400; }
.material-view:hover:not(:disabled) { color: var(--text); background: #ebebeb; }
.reader-backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(25, 26, 28, .27); }
.detail-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 41;
  width: min(560px, 100vw);
  min-height: 0;
  margin: 0;
  padding: 24px 28px 42px;
  overflow-y: auto;
  border: 0;
  border-left: 1px solid var(--border);
  border-radius: 0;
  box-shadow: -10px 0 30px rgba(0, 0, 0, .06);
  background: #fff;
}
.detail-head h2 { font-size: 18px; }
.reader-close { flex: 0 0 auto; border: 0; color: var(--text-secondary); font-weight: 400; }
.detail-summary { padding: 10px 0 14px; }
.reader-body { min-height: 160px; padding: 10px 0 22px; }
.reader-text { margin: 0; color: var(--text); font-family: inherit; font-size: 13px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.collapse-toggle { width: 100%; padding: 10px 0; border: 0; border-top: 1px solid var(--border); border-radius: 0; color: var(--text-secondary); background: #fff; text-align: left; font-size: 12px; font-weight: 400; }
.collapse-toggle:hover:not(:disabled) { background: #fff; color: var(--text); }
.detail-panel .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.detail-panel .chunk-list { max-height: none; overflow: visible; }
@media (max-width: 760px) {
  .upload-panel { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .upload-panel .upload-submit, .upload-panel .upload-cancel { justify-self: start; }
}
@media (max-width: 560px) {
  .upload-panel { grid-template-columns: minmax(0, 1fr); }
  .upload-panel .upload-submit, .upload-panel .upload-cancel { justify-self: stretch; }
  .material-item { grid-template-columns: 22px minmax(0, 1fr) 52px; gap: 7px; }
  .material-item .material-status { display: none; }
  .detail-panel { width: 100vw; padding: 18px 16px 34px; }
}

.upload-panel { border-radius: 12px; background: #fff; }
.list-panel { overflow: hidden; border: 1px solid var(--border); border-radius: 14px; }
.material-item { padding-inline: 10px; }
.material-item--selected, .material-item--selected:hover:not(:disabled) { background: #eef5ff; }
.material-view { border-radius: 8px; }
.detail-panel { border-radius: 16px 0 0 16px; }
.reader-text { font-size: 14px; white-space: normal; }
@media (max-width: 560px) {
  .material-item { padding-inline: 8px; }
  .detail-panel { border-radius: 0; }
}
.materials-list-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.materials-list-head > div { display: flex; align-items: baseline; gap: 9px; }
.materials-list-head h2 { margin: 0; }
.materials-list-head input { width: min(230px, 48%); min-height: 32px; padding: 5px 10px; border: 1px solid var(--border); border-radius: 9px; background: #fff; font-size: 12px; }
.materials-list-head input::placeholder { color: var(--text-tertiary); }
.materials-pagination { border-radius: 0 0 14px 14px; }
/* 资料列表以“打开阅读”为主，来源信息退到第二行。 */
.materials-page { width: min(1080px, 100%); }
.materials-header { align-items: center; margin: 3px 0 22px; }
.materials-header p { margin: 0; color: var(--text-tertiary); font-size: 13px; }
.materials-header-actions { gap: 10px; }
.materials-header-actions .refresh-button { border-color: transparent; color: var(--text-secondary); background: transparent; }
.materials-header-actions .refresh-button:hover:not(:disabled) { background: #f4f7fb; }
.materials-header-actions .upload-toggle { min-height: 35px; padding-inline: 14px; border-radius: 9px; font-size: 12px; }
.stats-row { gap: 7px 20px; margin-bottom: 16px; padding: 0 0 13px; border-bottom-color: #edf0f4; }
.stats-row strong { font-size: 13px; }
.stats-row small { font-size: 11px; }
.list-panel { border-color: #e5eaf0; border-radius: 12px; }
.materials-list-head { min-height: 68px; padding: 13px 18px; border-bottom-color: #edf0f4; }
.materials-list-head h2 { font-size: 16px; }
.materials-list-head input { width: min(250px, 46%); min-height: 35px; padding-inline: 12px; border-color: #e0e6ee; background: #fbfcfe; font-size: 12px; }
.materials-list-head input:focus { border-color: #9bb9dc; background: #fff; outline: 2px solid #e3effc; }
.material-list li:not(:last-child) { border-bottom-color: #edf0f4; }
.material-item { grid-template-columns: 26px minmax(0, 1fr) 78px 65px; gap: 13px; min-height: 70px; padding: 10px 18px; }
.material-item:hover:not(:disabled) { background: #f8fafc; }
.material-item--selected, .material-item--selected:hover:not(:disabled) { background: #f3f8fe; }
.file-glyph { width: 20px; height: 25px; border-color: #9eb2c7; border-radius: 3px; }
.file-glyph::before { background: #a9bdcf; box-shadow: 0 4px #a9bdcf, 0 8px #a9bdcf; }
.material-item__main { gap: 4px; }
.material-item__title { font-size: 14px; font-weight: 570; }
.material-item__sub { color: var(--text-tertiary); font-size: 11px; }
.material-status { font-size: 11px; }
.material-view { display: inline-flex; align-items: center; justify-content: flex-end; gap: 5px; min-height: 30px; color: #365c82; font-weight: 530; }
.material-view:hover:not(:disabled) { color: #23476e; background: transparent; text-decoration: underline; }
.materials-pagination { padding: 12px 0; border-top-color: #edf0f4; }
.detail-panel { width: min(620px, 100vw); padding: 29px 36px 44px; box-shadow: -16px 0 45px rgba(20, 38, 58, .09); }
.detail-head h2 { font-size: 20px; line-height: 1.4; }
.reader-body { padding-top: 18px; }
.reader-text { font-size: 15px; line-height: 1.9; }
@media (max-width: 560px) {
  .materials-list-head input { width: min(170px, 53%); }
  .materials-header { margin-bottom: 14px; }
  .materials-header p { font-size: 12px; }
  .material-item { grid-template-columns: 22px minmax(0, 1fr) auto; gap: 9px; min-height: 66px; padding-inline: 12px; }
  .material-item .material-view { padding-inline: 4px; }
  .detail-panel { width: 100vw; padding: 20px 18px 36px; }
}
.materials-layout .list-panel { overflow: hidden; border: 1px solid #e8edf2; border-radius: 16px; background: #fff; box-shadow: 0 4px 24px rgb(25 43 65 / 3%); }
.materials-list-head { padding: 18px 20px; background: #fcfdfe; }
.materials-list-head input { border-radius: 9px; border-color: #e5eaf0; background: #fff; }
.material-item { padding-block: 17px; }
.materials-pagination { justify-content: space-between; gap: 12px; padding: 16px 20px; border-radius: 0; }
.materials-page-buttons { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; }
.materials-page-buttons button { min-width: 30px; min-height: 30px; border-radius: 7px; font-variant-numeric: tabular-nums; }
.materials-page-buttons button[aria-current="page"] { color: #345c85; background: #edf4fc; font-weight: 600; }
.materials-entry-range, .materials-page-status { color: var(--text-tertiary); white-space: nowrap; font-size: 11px; }
@media (max-width: 760px) {
  .materials-pagination { flex-wrap: wrap; }
  .materials-page-buttons { order: 3; flex-basis: 100%; }
}
@media (max-width: 560px) {
  .materials-list-head { padding-inline: 12px; }
  .materials-pagination { padding: 13px 12px; }
}
</style>
