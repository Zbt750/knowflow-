<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "../api/client";
import {
  createChatSession,
  deleteChatSession,
  fetchChatMessages,
  fetchFollowupCandidates,
  listChatSessions,
  renameChatSession,
  streamChatAnswer,
  type ChatMessage,
  type ChatMode,
  type ChatSession,
  type FollowupCandidate,
  type MatchedKp,
  type Citation,
} from "../api/chat";
import { countReadyMaterials } from "../api/materials";
import { appendQuestions, fetchToday } from "../api/study";
import { isTodayActive, type TodayActive } from "../types/practice";
import { useAsyncTask } from "../composables/useAsyncTask";
import MarkdownContent from "../components/MarkdownContent.vue";

defineOptions({ name: "ChatPage" });

const sessionId = ref<string | null>(null);
const sessions = ref<ChatSession[]>([]);
const messages = ref<ChatMessage[]>([]);
const question = ref("");
const quotedAnswers = ref<Array<{ id: string; text: string }>>([]);
const answerSelection = ref<{ text: string; left: number; top: number } | null>(null);
// 统一状态（阶段 E）：页面的「加载中 / 失败」这一对状态由 pageTask 承载，
// 页面不再自己维护 loading 布尔 + 一个 error 字符串。
// `error` 与 `loading` 仍作为模板绑定的名字保留（testid 与文案契约不变）。
const pageTask = useAsyncTask<void>(null, {
  fallbackMessage: "无法加载问答页面",
});
const loading = computed(() => pageTask.state.value === "loading");
// `error` 仍由页面持有：它的文案要按业务分支细分（新建会话失败、改名失败、
// 删除失败、追练追加失败、上游未配置…），不适合塞进一个统一映射表。
// 页面加载失败这一种情况由 pageTask.state==='error' 决定，见 onMounted。
const error = ref("");
// `sending` 保留为页面自身的业务状态：它是**一次 SSE 流的过程标志**，
// 由流内多个分支（错误帧、断连、取消）决定何时复位，
// 与「一次请求的 submitting」不是同一个语义，硬套 submit() 反而会藏掉流的状态。
const sending = ref(false);
type StreamStage = "retrieving" | "generating" | "streaming";
const streamStage = ref<StreamStage>("retrieving");
const activeStreamMessageId = ref<string | null>(null);
const streamElapsedSeconds = ref(0);
const streamStageLabel = computed(() => {
  if (streamStage.value === "retrieving") return "正在检索资料…";
  if (streamStage.value === "generating") return "资料已检索，正在组织回答…";
  return "正在输出回答…";
});
let streamTimer: number | null = null;

function startStreamTimer(): void {
  streamElapsedSeconds.value = 0;
  if (streamTimer !== null) window.clearInterval(streamTimer);
  streamTimer = window.setInterval(() => { streamElapsedSeconds.value += 1; }, 1000);
}

function stopStreamTimer(): void {
  if (streamTimer !== null) window.clearInterval(streamTimer);
  streamTimer = null;
}
const selectedMode = ref<ChatMode>("user");
const compactSidebar = ref(typeof window !== "undefined" && window.matchMedia("(max-width: 980px)").matches);
const updateSidebarMode = () => { compactSidebar.value = window.matchMedia("(max-width: 980px)").matches; };
const readyByMode = ref<Record<ChatMode, number>>({ user: 0, builtin: 0 });
const scrollBox = ref<HTMLElement | null>(null);
const openCitationIds = ref(new Set<string>());
const expandedMessageIds = ref(new Set<string>());
const followups = ref<FollowupCandidate[]>([]);
const followupsVisible = ref(false);
const findingFollowups = ref(false);
const dismissedSuggestionAnswerId = ref<string | null>(null);
let followupRequestVersion = 0;
const selectedFollowupIds = ref<string[]>([]);
const todayPlan = ref<TodayActive | null>(null);
const appendingFollowups = ref(false);
const feedbackNotice = ref("");
let controller: AbortController | null = null;
const router = useRouter();
const route = useRoute();

const PINNED_SESSIONS_KEY = "kaoyan-chat-pinned-sessions";
const pinnedSessionIds = ref(new Set<string>());
const orderedSessions = computed(() => [...sessions.value].sort((a, b) =>
  Number(pinnedSessionIds.value.has(b.session_id)) - Number(pinnedSessionIds.value.has(a.session_id)),
));
const contextSession = ref<ChatSession | null>(null);
const contextPosition = ref({ left: 0, top: 0 });

function loadPinnedSessions(): void {
  try {
    const stored = JSON.parse(window.localStorage.getItem(PINNED_SESSIONS_KEY) ?? "[]");
    if (Array.isArray(stored)) pinnedSessionIds.value = new Set(stored.filter((id): id is string => typeof id === "string"));
  } catch {
    pinnedSessionIds.value = new Set();
  }
}
function togglePinnedSession(target: ChatSession): void {
  const next = new Set(pinnedSessionIds.value);
  if (next.has(target.session_id)) next.delete(target.session_id);
  else next.add(target.session_id);
  pinnedSessionIds.value = next;
  try {
    window.localStorage.setItem(PINNED_SESSIONS_KEY, JSON.stringify([...next]));
  } catch {
    error.value = "此浏览器无法保存置顶状态";
  }
}
function openContextMenuAt(left: number, top: number, target: ChatSession): void {
  if (sending.value) return;
  contextSession.value = target;
  contextPosition.value = {
    left: Math.max(8, Math.min(left, window.innerWidth - 186)),
    top: Math.max(8, Math.min(top, window.innerHeight - 188)),
  };
  void nextTick(() => document.querySelector<HTMLElement>(".conversation-menu button")?.focus());
}
function openContextMenu(event: MouseEvent, target: ChatSession): void {
  event.preventDefault();
  openContextMenuAt(event.clientX, event.clientY, target);
}
function onConversationKeydown(event: KeyboardEvent, target: ChatSession): void {
  if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
  event.preventDefault();
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  openContextMenuAt(rect.left + 18, rect.bottom, target);
}
function openCompactMenu(event: MouseEvent, target: ChatSession): void {
  event.stopPropagation();
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  openContextMenuAt(rect.left, rect.bottom, target);
}
function closeContextMenu(): void {
  contextSession.value = null;
}
function onDocumentPointerDown(event: PointerEvent): void {
  if (!(event.target instanceof Element) || !event.target.closest(".conversation-menu")) closeContextMenu();
}
function onContextMenuEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") closeContextMenu();
}
async function shareSession(target: ChatSession): Promise<void> {
  const href = router.resolve({ path: "/chat", query: { session_id: target.session_id } }).href;
  const url = new URL(href, window.location.origin).href;
  try {
    await navigator.clipboard.writeText(url);
    feedbackNotice.value = "会话链接已复制；接收者需能访问同一套服务。";
  } catch {
    window.prompt("复制会话链接", url);
  }
}
async function runContextAction(action: "rename" | "share" | "pin" | "delete"): Promise<void> {
  const target = contextSession.value;
  closeContextMenu();
  if (!target) return;
  if (action === "rename") await renameSession(target);
  else if (action === "share") await shareSession(target);
  else if (action === "pin") togglePinnedSession(target);
  else await deleteSession(target);
}

const currentModeLabel = computed(() => selectedMode.value === "user" ? "我的资料" : "内置资料");
const hasReadyMaterials = computed(() => readyByMode.value[selectedMode.value] > 0);
const canSend = computed(() => Boolean((question.value.trim() || quotedAnswers.value.length) && !sending.value && hasReadyMaterials.value));
const questionIdsInTodayPlan = computed(() => new Set(todayPlan.value?.items.map((item) => item.question_id) ?? []));
const canAppendFollowups = computed(() => Boolean(todayPlan.value && selectedFollowupIds.value.length && !appendingFollowups.value));

/** 只针对对话末尾这条已完成回答显示建议，失败或生成中的消息不能复用旧建议。 */
const lastCompletedAnswer = computed(() => {
  const item = messages.value[messages.value.length - 1];
  return item?.role === "assistant" && item.status === "completed" ? item : null;
});
const showAnswerSuggestions = computed(() => Boolean(
  selectedMode.value === "builtin"
  && lastCompletedAnswer.value && !sending.value && !question.value.trim()
  && dismissedSuggestionAnswerId.value !== lastCompletedAnswer.value.message_id,
));

function modeLabel(mode: ChatMode): string {
  return mode === "user" ? "我的资料" : "内置资料";
}

/** 新问题或切换会话时，收起属于上一条回答的动作和候选题。 */
function resetAnswerActions(): void {
  followupRequestVersion += 1;
  dismissedSuggestionAnswerId.value = null;
  findingFollowups.value = false;
  followupsVisible.value = false;
  followups.value = [];
  selectedFollowupIds.value = [];
}
function clearQuotedAnswerContext(): void {
  quotedAnswers.value = [];
  answerSelection.value = null;
}
function onAnswerTextSelection(): void {
  const selection = window.getSelection();
  const selectedText = selection?.toString().trim();
  const anchor = selection?.anchorNode;
  const anchorElement = anchor instanceof Element ? anchor : anchor?.parentElement;
  if (!selectedText || !anchorElement?.closest(".message-bubble--selectable")) {
    answerSelection.value = null;
    return;
  }
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  const rect = range?.getBoundingClientRect();
  if (!rect) return;
  answerSelection.value = {
    text: selectedText.slice(0, 2000),
    left: Math.max(8, Math.min(rect.left, window.innerWidth - 246)),
    top: rect.top > 58 ? rect.top - 48 : rect.bottom + 8,
  };
}
function onSelectionPointerDown(event: PointerEvent): void {
  if (!(event.target instanceof Element)) return;
  if (event.target.closest(".selection-quote-action, .message-bubble--selectable")) return;
  answerSelection.value = null;
}
function addSelectedAnswerToComposer(): void {
  const selected = answerSelection.value?.text.trim();
  if (!selected) return;
  quotedAnswers.value.push({
    id: String(Date.now()) + "-" + Math.random().toString(36).slice(2, 8),
    text: selected,
  });
  answerSelection.value = null;
  window.getSelection()?.removeAllRanges();
  void nextTick(() => document.getElementById("chat-question")?.focus());
}
function removeQuotedAnswer(id: string): void {
  quotedAnswers.value = quotedAnswers.value.filter((item) => item.id !== id);
}
function messageIsLong(message: ChatMessage): boolean {
  return message.role === "assistant" && message.content.length > 360;
}
function formatResponseDuration(durationMs: number | null | undefined): string {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs < 0) return "耗时未记录";
  if (durationMs < 100) return "耗时不足 0.1 秒";
  const seconds = durationMs / 1000;
  if (seconds < 60) return `耗时 ${seconds.toFixed(1)} 秒`;
  return `耗时 ${Math.floor(seconds / 60)} 分 ${(seconds % 60).toFixed(1)} 秒`;
}
function isExpanded(messageId: string): boolean {
  return expandedMessageIds.value.has(messageId);
}
function toggleExpanded(messageId: string): void {
  const next = new Set(expandedMessageIds.value);
  next.has(messageId) ? next.delete(messageId) : next.add(messageId);
  expandedMessageIds.value = next;
}
function citationsOpen(messageId: string): boolean {
  return openCitationIds.value.has(messageId);
}
function toggleCitations(messageId: string): void {
  const next = new Set(openCitationIds.value);
  next.has(messageId) ? next.delete(messageId) : next.add(messageId);
  openCitationIds.value = next;
}
function openCitation(citation: Citation): void {
  void router.push({
    path: "/materials",
    query: { material_id: citation.material_id, chunk_id: citation.chunk_id },
  });
}
async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight;
}

async function refreshMaterials(): Promise<void> {
  const [user, builtin] = await Promise.all([
    countReadyMaterials("user"),
    countReadyMaterials("builtin"),
  ]);
  readyByMode.value = { user, builtin };
}
/**
 * 取历史会话。
 *
 * 必须**按当前范围过滤**：篇 01 规定两种问答模式严格隔离（检索范围、matched_kp、
 * 追练推荐、学习事件都不同），混在一个列表里用户分不清哪条属于哪个范围。
 * 后端同时不再返回没有任何消息的空会话，所以列表里每一条都能点开看。
 */
async function refreshSessions(): Promise<void> {
  sessions.value = await listChatSessions(selectedMode.value);
}
async function refreshTodayPlan(): Promise<void> {
  const response = await fetchToday();
  todayPlan.value = isTodayActive(response) ? response : null;
}
async function openSession(session: ChatSession): Promise<void> {
  if (sending.value) return;
  error.value = "";
  feedbackNotice.value = "";
  resetAnswerActions();
  clearQuotedAnswerContext();
  sessionId.value = session.session_id;
  selectedMode.value = session.mode;
  messages.value = await fetchChatMessages(session.session_id);
  if (route.query.session_id && route.query.session_id !== session.session_id) await router.replace({ path: "/chat" });
  await scrollToBottom();
}
/**
 * 开一段**尚未落库**的新对话。
 *
 * 为什么不在这里建会话：见 `changeScope` 的说明。会话统一推迟到
 * `send()` 里「用户真的发出第一条问题」时才创建。
 */
function startDraft(): void {
  if (sending.value) return;
  error.value = "";
  feedbackNotice.value = "";
  resetAnswerActions();
  clearQuotedAnswerContext();
  sessionId.value = null;
  messages.value = [];
  if (route.query.session_id) void router.replace({ path: "/chat" });
}
/**
 * 切换资料范围。
 *
 * **不再立刻创建会话。** 原来每次切换都会 `createChatSession`，于是开发库里
 * 94 条未归档会话有 46 条是空壳（builtin 23 / user 23）—— 一次性用完就丢的
 * 「新对话」把历史列表冲成噪声，用户根本翻不动。
 *
 * 现在切换只做两件事：改「当前范围」并重置为一段草稿、把历史列表换成该范围的。
 * 会话在 `send()` 里才落库，所以历史里出现的每一条都至少问过一个问题。
 */
async function changeScope(mode: ChatMode): Promise<void> {
  if (sending.value) return;
  selectedMode.value = mode;
  startDraft();
  await refreshSessions().catch(() => undefined);
}
async function renameSession(target: ChatSession): Promise<void> {
  if (sending.value) return;
  const nextTitle = window.prompt("会话名称", target.title);
  const title = nextTitle?.trim();
  if (!title || title === target.title) return;
  try {
    const updated = await renameChatSession(target.session_id, title);
    sessions.value = sessions.value.map((item) => item.session_id === updated.session_id ? updated : item);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "会话改名失败";
  }
}
/**
 * 永久删除历史列表里的任意一条会话（不再局限于「当前正在看的那条」）。
 *
 * 后端 `DELETE /chat/sessions/{id}` 是**物理删除**：会话行连同它的消息与引用
 * 一起从库里移除（见 `delete_session` 的 docstring）。所以确认框必须把话说死——
 * 这是**不可恢复**的操作，不能让用户以为只是从列表里收起来。
 */
async function deleteSession(target: ChatSession): Promise<void> {
  if (sending.value) return;
  if (!window.confirm(`删除会话「${target.title}」？\n\n此操作不可恢复：该会话的问答记录与引用会被永久删除。`)) return;
  try {
    await deleteChatSession(target.session_id);
    sessions.value = sessions.value.filter((item) => item.session_id !== target.session_id);
    if (pinnedSessionIds.value.has(target.session_id)) togglePinnedSession(target);
    // 删掉的正是当前打开的那条 → 自动切到下一条；一条都不剩就回到空白草稿。
    if (target.session_id === sessionId.value) {
      const next = orderedSessions.value[0];
      if (next) await openSession(next);
      else startDraft();
    }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "会话删除失败";
  }
}
async function copyAnswer(content: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(content);
    feedbackNotice.value = "回答已复制";
  } catch {
    feedbackNotice.value = "浏览器未允许复制，请手动选择文本";
  }
}

async function send(): Promise<void> {
  if (sending.value || (!question.value.trim() && !quotedAnswers.value.length)) return;
  if (!hasReadyMaterials.value) {
    error.value = `当前「${currentModeLabel.value}」没有已完成索引的资料。请切换资料范围，或先到“资料”页完成上传和索引。`;
    return;
  }
  const quoteContext = quotedAnswers.value.map((item) =>
    "引用的回答片段：\n" + item.text.split("\n").map((line) => "> " + line).join("\n"),
  ).join("\n\n");
  const text = [quoteContext, question.value.trim()].filter(Boolean).join("\n\n");
  error.value = "";
  feedbackNotice.value = "";
  resetAnswerActions();
  sending.value = true;
  // 新对话在这里才落库：只有用户真的发出第一条问题，才值得在历史里占一条。
  // 之前是「点新建/切范围就建」，导致库里一半会话是没有任何消息的空壳。
  let id = sessionId.value;
  if (id === null) {
    try {
      const created = await createChatSession("新对话", selectedMode.value);
      id = created.session_id;
      sessionId.value = id;
    } catch (caught) {
      sending.value = false;
      // 输入框内容保留：创建失败时用户可以直接再发一次，不用重打问题。
      error.value = caught instanceof ApiError ? caught.message : "无法新建会话，请重试";
      return;
    }
  }
  question.value = "";
  clearQuotedAnswerContext();
  const localUserId = `local-user-${Date.now()}`;
  const localAssistantId = `streaming-${Date.now()}`;
  messages.value.push({ message_id: localUserId, role: "user", content: text, status: "completed", matched_kp_id: null, citations: [] });
  const assistant = reactive<ChatMessage>({ message_id: localAssistantId, role: "assistant", content: "", status: "generating", matched_kp_id: null, citations: [] });
  messages.value.push(assistant);
  activeStreamMessageId.value = localAssistantId;
  streamStage.value = "retrieving";
  startStreamTimer();
  controller = new AbortController();
  await scrollToBottom();
  try {
    await streamChatAnswer(id, text, async (event, data) => {
      if (event === "meta") {
        assistant.message_id = String(data.message_id);
        activeStreamMessageId.value = assistant.message_id;
        streamStage.value = "generating";
      }
      if (event === "delta") {
        streamStage.value = "streaming";
        assistant.content += String(data.text ?? "");
        await scrollToBottom();
      }
      if (event === "citations") {
        assistant.citations = (data.citations as Citation[] | undefined) ?? [];
      }
      if (event === "done") {
        assistant.status = "completed";
        assistant.response_duration_ms = typeof data.response_duration_ms === "number" ? data.response_duration_ms : null;
        assistant.matched_kp_id = data.matched_kp_id ? String(data.matched_kp_id) : null;
        // 归因依据由后端给出并落库，前端只负责显示，不自己算。
        assistant.matched_kp = (data.matched_kp as MatchedKp | null | undefined) ?? null;
        assistant.citations = (data.citations as Citation[] | undefined) ?? assistant.citations;
      }
      if (event === "error") {
        assistant.status = "failed";
        // 规格 2.5：llm_not_configured → 明确「尚未配置问答模型」并给出配置指引；
        // generation_failed / retrieval_failed → 该条消息标记失败，只提供普通重试。
        const code = String(data.code ?? "");
        error.value =
          code === "llm_not_configured"
            ? "尚未配置问答模型：请在项目根目录的 .env 里配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重启后端。"
            : code === "retrieval_timeout"
              ? "资料检索超过 30 秒，已停止本次请求。请确认资料已完成索引，或缩小问题范围后重试。"
            : code === "retrieval_failed"
              ? "检索暂时失败（向量库或模型不可用），可以稍后重试这次提问。"
              : String(data.message ?? "回答生成失败");
      }
    }, controller.signal);
    if (assistant.status === "generating") {
      assistant.status = "failed";
      error.value = "回答连接已结束，但没有收到完成状态，请重试。";
    }
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      assistant.status = "cancelled";
      feedbackNotice.value = "已停止生成；这次未完成回答不会作为可用引用。";
    } else {
      assistant.status = "failed";
      if (caught instanceof ApiError) {
        error.value =
          caught.code === "llm_not_configured"
            ? "尚未配置问答模型：请在项目根目录的 .env 里配置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重启后端。"
            : caught.code === "retrieval_timeout"
              ? "资料检索超过 30 秒，已停止本次请求。请确认资料已完成索引，或缩小问题范围后重试。"
            : caught.message;
      } else {
        error.value = "无法连接问答服务";
      }
    }
  } finally {
    sending.value = false;
    activeStreamMessageId.value = null;
    stopStreamTimer();
    controller = null;
    await refreshSessions().catch(() => undefined);
    await fetchChatMessages(id).then((items) => { if (sessionId.value === id) messages.value = items; }).catch(() => undefined);
    await scrollToBottom();
  }
}
function cancel(): void {
  controller?.abort();
}
function followupAlreadyInTodayPlan(candidate: FollowupCandidate): boolean {
  return questionIdsInTodayPlan.value.has(candidate.question_id);
}
function toggleFollowup(candidate: FollowupCandidate): void {
  if (followupAlreadyInTodayPlan(candidate)) return;
  const next = new Set(selectedFollowupIds.value);
  next.has(candidate.question_id) ? next.delete(candidate.question_id) : next.add(candidate.question_id);
  selectedFollowupIds.value = [...next];
}
type AnswerAction = "rephrase" | "steps" | "example";
function skipSuggestions(): void {
  followupRequestVersion += 1;
  dismissedSuggestionAnswerId.value = lastCompletedAnswer.value?.message_id ?? null;
  findingFollowups.value = false;
  followupsVisible.value = false;
  selectedFollowupIds.value = [];
}
async function runAnswerAction(action: AnswerAction): Promise<void> {
  if (!lastCompletedAnswer.value || sending.value) return;
  // 检索仍以原问题为中心；只发「换种讲法」会让资料检索丢失主题。
  const previousQuestion = messages.value[messages.value.length - 2];
  const topic = previousQuestion?.role === "user" ? previousQuestion.content.slice(0, 600) : "刚才的问题";
  const instruction = {
    rephrase: "请换一种更容易理解的方式解释，仍然只依据资料。",
    steps: "请把关键步骤逐步拆开，说明每一步为什么这样做。",
    example: "请结合资料举一个具体例子；如果资料没有合适例子，请明确说明。",
  }[action];
  question.value = `关于“${topic}”：${instruction}`;
  await send();
}
async function showFollowups(): Promise<void> {
  const id = sessionId.value;
  const answerId = lastCompletedAnswer.value?.message_id;
  if (!id || !answerId || selectedMode.value !== "builtin" || findingFollowups.value) return;
  const requestVersion = ++followupRequestVersion;
  followupsVisible.value = true;
  findingFollowups.value = true;
  followups.value = [];
  selectedFollowupIds.value = [];
  try {
    await refreshTodayPlan().catch(() => { todayPlan.value = null; });
    const response = await fetchFollowupCandidates(id, answerId);
    if (requestVersion !== followupRequestVersion || sessionId.value !== id || lastCompletedAnswer.value?.message_id !== answerId) return;
    followups.value = response.candidates;
  } catch (caught) {
    if (requestVersion === followupRequestVersion) {
      error.value = caught instanceof ApiError ? caught.message : "读取追练候选失败";
      followupsVisible.value = false;
    }
  } finally {
    if (requestVersion === followupRequestVersion) findingFollowups.value = false;
  }
}
async function appendSelectedFollowups(): Promise<void> {
  if (!todayPlan.value || !canAppendFollowups.value) return;
  const selected = [...selectedFollowupIds.value];
  if (!window.confirm(`确认将 ${selected.length} 道已有题库题目加入今日练习卷？`)) return;
  appendingFollowups.value = true;
  try {
    const response = await appendQuestions(todayPlan.value.plan_id, selected);
    todayPlan.value = isTodayActive(response) ? response : null;
    selectedFollowupIds.value = [];
    feedbackNotice.value = "已将选中的已有题库题目追加到今日练习卷。请在“今日学习”中完成作答和自评。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "追加到今日练习卷失败";
  } finally {
    appendingFollowups.value = false;
  }
}
onMounted(async () => {
  await pageTask.run(async () => {
    await Promise.all([refreshMaterials(), refreshTodayPlan()]);
    // 先不带 mode 取一次历史：**最近用过的那条会话的模式**就是用户上次待的地方，
    // 用它作为默认范围。这样刷新页面会回到原处，而不是每次跳回另一个范围。
    const recent = await listChatSessions();
    const fallback: ChatMode = readyByMode.value.user > 0 || readyByMode.value.builtin === 0 ? "user" : "builtin";
    const sharedId = typeof route.query.session_id === "string" ? route.query.session_id : null;
    const initial = sharedId ? recent.find((item) => item.session_id === sharedId) : recent[0];
    selectedMode.value = initial?.mode ?? fallback;
    await refreshSessions();
    // 分享链接优先打开指定会话；普通访问仍回到最近使用的会话。
    if (initial) await openSession(initial);
    else startDraft();
    if (sharedId && !initial) error.value = "分享的会话不存在或已删除";
  });
  // 页面级加载失败：把统一状态给出的文案（含非 ApiError 的兜底）接到页面提示上。
  if (pageTask.state.value === "error") error.value = pageTask.errorMessage.value ?? "无法加载问答页面";
});
onMounted(() => {
  loadPinnedSessions();
  window.addEventListener("resize", updateSidebarMode);
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("pointerdown", onSelectionPointerDown);
  window.addEventListener("keydown", onContextMenuEscape);
});
onBeforeUnmount(() => {
  controller?.abort();
  stopStreamTimer();
  window.removeEventListener("resize", updateSidebarMode);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("pointerdown", onSelectionPointerDown);
  window.removeEventListener("keydown", onContextMenuEscape);
});
</script>

<template>
  <section class="chat-workspace" aria-label="可信问答">
    <Teleport to="#chat-sidebar-slot" :disabled="compactSidebar">
    <aside class="conversation-sidebar" aria-label="会话历史">
      <div class="sidebar-head">
        <h2>对话</h2>
        <button class="icon-button" type="button" title="新建对话" :disabled="sending" @click="startDraft">＋</button>
      </div>
      <div class="scope-picker" aria-label="选择资料范围">
        <button type="button" class="scope-switch" data-testid="scope-switch" :disabled="sending" :aria-label="`当前${currentModeLabel}，切换到${selectedMode === 'user' ? '内置资料' : '我的资料'}`" @click="changeScope(selectedMode === 'user' ? 'builtin' : 'user')">
          <span>当前：{{ currentModeLabel }} <small>{{ readyByMode[selectedMode] }} 份</small></span>
          <span aria-hidden="true">切换 ↕</span>
        </button>
      </div>
      <div class="history-label">历史会话</div>
      <div class="conversation-list">
        <div
          v-for="item in orderedSessions"
          :key="item.session_id"
          class="conversation-row"
          :class="{ selected: item.session_id === sessionId, pinned: pinnedSessionIds.has(item.session_id) }"
          tabindex="0"
          :title="'右键打开会话操作：' + item.title"
          @contextmenu="openContextMenu($event, item)"
          @keydown="onConversationKeydown($event, item)"
        >
          <button type="button" class="conversation-item" @click="openSession(item)">
            <span class="conversation-title">{{ item.title }}</span>
            <span v-if="pinnedSessionIds.has(item.session_id)" class="conversation-pinned">置顶</span>
            <small>{{ modeLabel(item.mode) }}</small>
          </button>
          <button v-if="compactSidebar" type="button" class="conversation-more" :aria-label="'会话操作：' + item.title" @click="openCompactMenu($event, item)">⋯</button>
        </div>
        <p v-if="!loading && sessions.length === 0" class="history-empty">还没有历史会话</p>
      </div>
    </aside>
    </Teleport>

    <main class="chat-main">
      <header class="chat-header">
        <p class="chat-source" data-testid="chat-source">资料来源：{{ currentModeLabel }}</p>
      </header>

      <p v-if="error" class="chat-notice chat-notice--error" role="alert">{{ error }} <RouterLink v-if="error.includes('尚未配置问答模型')" to="/settings">查看设置</RouterLink></p>
      <p v-if="feedbackNotice" class="chat-notice chat-notice--success">{{ feedbackNotice }}</p>
      <p v-if="!hasReadyMaterials" class="chat-notice chat-notice--setup">
        当前范围没有已经完成索引的资料。<RouterLink to="/materials">去资料页上传、查看索引状态或切换资料范围</RouterLink>。
      </p>

      <section ref="scrollBox" class="messages" aria-live="polite" :aria-busy="sending" @mouseup="onAnswerTextSelection" @keyup="onAnswerTextSelection">
        <div v-if="loading" class="empty-state">正在读取会话和资料状态…</div>
        <div v-else-if="messages.length === 0" class="empty-state">
          <strong>从一个资料内的问题开始</strong>
          <span>例如：这份资料中，阶段 D 的 SSE 事件顺序是什么？</span>
          <small>没有相关内容时，会显示资料范围或索引状态。</small>
        </div>

        <article v-for="message in messages" :key="message.message_id" class="message-row" :class="`message-row--${message.role}`">
          <div class="message-avatar" aria-hidden="true">{{ message.role === "user" ? "你" : "AI" }}</div>
          <div class="message-body">
            <div class="message-meta">{{ message.role === "user" ? "你的问题" : "资料问答助手" }}</div>
            <div v-if="message.role === 'assistant' && message.status === 'generating'" class="response-progress" role="status" data-testid="response-progress">
              <span v-if="message.message_id === activeStreamMessageId" class="response-progress__dots" aria-hidden="true"><i></i><i></i><i></i></span>
              <span>{{ message.message_id === activeStreamMessageId ? streamStageLabel : "这次回答尚未完成。" }}</span>
              <span v-if="message.message_id === activeStreamMessageId" class="response-progress__time" aria-hidden="true">{{ streamElapsedSeconds }} 秒</span>
            </div>
            <div v-if="message.status !== 'generating' || Boolean(message.content)" class="message-bubble" :class="{ 'message-bubble--collapsed': messageIsLong(message) && !isExpanded(message.message_id), 'message-bubble--selectable': message.role === 'assistant' && message.status === 'completed' }">
              <MarkdownContent v-if="message.role === 'assistant' && message.content" :text="message.content" />
              <MarkdownContent v-else-if="message.content && message.content.includes('\n> ')" :text="message.content" />
              <p v-else>{{ message.content || (message.status === 'cancelled' ? '已停止生成。' : '回答生成失败。') }}</p>
            </div>
            <button v-if="messageIsLong(message)" type="button" class="text-action" @click="toggleExpanded(message.message_id)">
              {{ isExpanded(message.message_id) ? "收起回答" : "展开完整回答" }}
            </button>
            <!--
              归因依据。
              归因结果决定「推荐哪些追练题」，所以它不能只给结论：
              这里明确告诉用户是哪一个引用片段（[C1]）把这次回答归到了哪个叶子知识点，
              用户据此就能自己判断这次归因对不对，而不是只能被动接受。
              只显示，不计算 —— 依据字段全部来自后端并已落库。
              只在「内置资料」模式显示：「我的资料」模式按契约不产生归因与追练推荐。
            -->
            <div
              v-if="message.role === 'assistant' && message.matched_kp && selectedMode === 'builtin'"
              class="attribution-box"
              data-testid="attribution-box"
            >
              <span class="attribution-box__label">归因依据</span>
              <template v-if="message.matched_kp.attribution_label">
                这次回答被归到叶子知识点
                <strong data-testid="attribution-kp">{{
                  message.matched_kp.kp_name || message.matched_kp.kp_id
                }}</strong>
                ，依据是正文引用的
                <code data-testid="attribution-label">[{{ message.matched_kp.attribution_label }}]</code>
                （检索命中第 {{ message.matched_kp.source_rank }} 位<template
                  v-if="message.matched_kp.cosine !== null"
                  >，语义相关度 {{ message.matched_kp.cosine.toFixed(2) }}</template
                >）。
                <button
                  type="button"
                  class="text-action attribution-box__open"
                  @click="toggleCitations(message.message_id)"
                >
                  查看该片段
                </button>
              </template>
              <template v-else>
                这次回答被归到叶子知识点
                <strong data-testid="attribution-kp">{{
                  message.matched_kp.kp_name || message.matched_kp.kp_id
                }}</strong>
                ，依据是检索命中第 {{ message.matched_kp.source_rank }} 位的资料片段（该片段未被正文引用）。
              </template>
            </div>
            <div v-if="message.role === 'assistant' && message.citations.length" class="citation-box">
              <button type="button" class="citation-toggle" :aria-expanded="citationsOpen(message.message_id)" @click="toggleCitations(message.message_id)">
                引用 {{ message.citations.length }} 个资料片段 <span>{{ citationsOpen(message.message_id) ? "⌃" : "⌄" }}</span>
              </button>
              <ol v-if="citationsOpen(message.message_id)" class="citation-list">
                <li v-for="citation in message.citations" :key="citation.label">
                  <code>[{{ citation.label }}]</code>
                  <button type="button" class="citation-card" @click="openCitation(citation)">
                    <strong>{{ citation.material_title }}</strong>
                    <span>{{ citation.heading_path.join(" › ") || "未标注章节" }} · 第 {{ citation.ordinal + 1 }} 块</span>
                    <p>{{ citation.preview }}</p>
                    <small>chunk: {{ citation.chunk_id }}</small>
                  </button>
                </li>
              </ol>
            </div>
            <div v-if="message.role === 'assistant' && message.status === 'completed'" class="message-actions">
              <span class="response-duration" :title="message.response_duration_ms == null ? '旧回答没有保存耗时' : '包含资料检索与回答生成的总耗时'">{{ formatResponseDuration(message.response_duration_ms) }}</span>
              <button type="button" class="text-action" @click="copyAnswer(message.content)">复制</button>
            </div>
          </div>
        </article>
      </section>

      <section v-if="selectedMode === 'builtin' && followupsVisible" class="followup-card" data-testid="followup-candidates">
        <div><strong>相关题目</strong><small>从现有题库查找；由你决定是否加入今日学习。</small></div>
        <p v-if="findingFollowups" role="status">正在查找题目…</p>
        <p v-else-if="followups.length === 0" data-testid="followup-empty">这次回答没有可靠匹配到可用的题库题目。</p>
        <ol v-else class="followup-options">
          <li v-for="item in followups" :key="item.question_id">
            <label :class="{ 'followup-options--in-plan': followupAlreadyInTodayPlan(item) }">
              <input type="checkbox" :checked="selectedFollowupIds.includes(item.question_id)" :disabled="!todayPlan || followupAlreadyInTodayPlan(item) || appendingFollowups" @change="toggleFollowup(item)">
              <span>{{ item.stem }}</span>
              <span class="tag">{{ item.practice_status }}</span><span v-if="item.is_variant" class="tag">变式</span><span v-if="followupAlreadyInTodayPlan(item)" class="tag tag--muted">已在今日卷</span>
            </label>
          </li>
        </ol>
        <p v-if="!findingFollowups && followups.length && !todayPlan" class="followup-plan-hint">要加入练习，请先到<RouterLink to="/study">今日学习</RouterLink>生成今日练习卷。</p>
        <div v-if="todayPlan && followups.length" class="followup-confirm">
          <span>当前今日练习卷：{{ todayPlan.total_count }} 道</span>
          <button type="button" data-testid="append-followup-questions" :disabled="!canAppendFollowups" @click="appendSelectedFollowups">{{ appendingFollowups ? "追加中…" : `确认加入今日练习卷（${selectedFollowupIds.length}）` }}</button>
        </div>
      </section>

      <form class="composer" @submit.prevent="send">
        <div v-if="quotedAnswers.length" class="composer-quotes" aria-label="已引用的回答内容" data-testid="composer-quotes">
          <blockquote v-for="item in quotedAnswers" :key="item.id" class="composer-quote">
            <span class="composer-quote__label">引用回答</span>
            <p>{{ item.text }}</p>
            <button type="button" :aria-label="'移除引用：' + item.text.slice(0, 24)" @click="removeQuotedAnswer(item.id)">移除</button>
          </blockquote>
        </div>
        <div v-if="showAnswerSuggestions" class="composer-suggestions" aria-label="回答后的可选操作" data-testid="answer-suggestions">
          <button type="button" data-testid="action-rephrase" @click="runAnswerAction('rephrase')">换种讲法</button>
          <button type="button" data-testid="action-steps" @click="runAnswerAction('steps')">拆解步骤</button>
          <button type="button" data-testid="action-example" @click="runAnswerAction('example')">举个例子</button>
          <button type="button" data-testid="action-find-questions" :disabled="selectedMode !== 'builtin'" :title="selectedMode !== 'builtin' ? '仅内置资料模式可关联现有题库' : '从现有题库查找相关题目'" @click="showFollowups">找相关题目</button>
          <button type="button" class="composer-suggestions__skip" data-testid="action-skip" @click="skipSuggestions">跳过</button>
        </div>
        <label class="sr-only" for="chat-question">你的问题</label>
        <textarea id="chat-question" v-model="question" :disabled="sending" maxlength="4000" rows="1" placeholder="输入问题，或先选中回答内容作为引用…" @keydown.enter.exact.prevent="send" />
        <div class="composer-footer"><small>{{ hasReadyMaterials ? `将在「${currentModeLabel}」内检索` : "请先选择含有已索引资料的范围" }}</small><div><button v-if="sending" type="button" @click="cancel">停止生成</button><button class="send-button" type="submit" :disabled="!canSend">发送</button></div></div>
      </form>
    </main>
    <Teleport to="body">
      <div
        v-if="contextSession"
        class="conversation-menu"
        role="menu"
        aria-label="会话操作"
        :style="{ left: contextPosition.left + 'px', top: contextPosition.top + 'px' }"
        @pointerdown.stop
      >
        <button type="button" role="menuitem" @click="runContextAction('rename')">重命名</button>
        <button type="button" role="menuitem" @click="runContextAction('share')">分享链接</button>
        <button type="button" role="menuitem" @click="runContextAction('pin')">{{ pinnedSessionIds.has(contextSession.session_id) ? "取消置顶" : "置顶" }}</button>
        <button type="button" role="menuitem" class="conversation-menu__danger" @click="runContextAction('delete')">删除</button>
      </div>
      <div
        v-if="answerSelection"
        class="selection-quote-action"
        role="toolbar"
        aria-label="选中回答操作"
        data-testid="selection-quote-action"
        :style="{ left: answerSelection.left + 'px', top: answerSelection.top + 'px' }"
        @pointerdown.prevent
      >
        <span>已选中回答内容</span>
        <button type="button" data-testid="quote-selected-answer" @click="addSelectedAnswerToComposer">引用到输入框</button>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.chat-workspace { display: grid; grid-template-columns: 236px minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 7px; background: #fff; }
.conversation-sidebar { display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 12px 8px 8px; border-right: 1px solid var(--border); background: #fafafa; }
.sidebar-head, .chat-header, .composer-footer { display: flex; justify-content: space-between; gap: 10px; }
.sidebar-head { align-items: center; min-height: 32px; padding: 0 5px; }
.sidebar-head > h2 { margin: 0; font-size: 13px; font-weight: 600; }
.icon-button { display: grid; width: 28px; min-height: 28px; padding: 0; place-items: center; border: 0; background: transparent; font-size: 18px; }
.icon-button:hover:not(:disabled) { background: var(--hover); }
.sidebar-hint { margin: 10px 6px 5px; color: var(--text-tertiary); font-size: 10px; font-weight: 600; }
.scope-picker { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; margin: 0 3px 14px; padding: 2px; border: 1px solid var(--border); border-radius: 6px; background: #f1f1f1; }
.scope-picker button { min-height: 29px; padding: 4px 3px; border: 0; border-radius: 4px; color: var(--text-secondary); background: transparent; font-size: 10px; }
.scope-picker button:hover:not(:disabled) { background: #e8e8e8; }
.scope-picker button.active { color: var(--text); background: #fff; }
.scope-picker button span { margin-left: 2px; color: var(--text-tertiary); }
.history-label { margin: 0 6px 6px; color: var(--text-tertiary); font-size: 10px; font-weight: 600; }
.conversation-list { display: grid; align-content: start; gap: 1px; min-height: 0; overflow-y: scroll; overscroll-behavior: contain; padding: 0 3px 2px 0; scrollbar-width: thin; scrollbar-color: #b8babd transparent; }
.conversation-list::-webkit-scrollbar { width: 8px; }
.conversation-list::-webkit-scrollbar-track { background: transparent; }
.conversation-list::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 7px; background: #b8babd; background-clip: padding-box; }
.conversation-list::-webkit-scrollbar-thumb:hover { background: #96989c; background-clip: padding-box; }
.conversation-row { display: flex; align-items: center; gap: 1px; border-radius: 5px; }
.conversation-row:hover { background: #ededed; }
.conversation-row.selected { background: #e5e5e5; }
.conversation-item { display: grid; flex: 1; min-width: 0; gap: 1px; min-height: 42px; padding: 6px 3px 6px 8px; border: 0; background: transparent; text-align: left; }
.conversation-item:hover:not(:disabled) { background: transparent; }
.conversation-title { overflow: hidden; font-size: 11px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.conversation-item small, .history-empty { color: var(--text-tertiary); font-size: 9px; }
.conversation-delete { display: grid; flex: 0 0 23px; width: 23px; min-height: 23px; margin-right: 3px; padding: 0; place-items: center; border: 0; color: transparent; background: transparent; }
.conversation-row:hover .conversation-delete, .conversation-row:focus-within .conversation-delete { color: #8d8f93; }
.conversation-delete:hover:not(:disabled) { color: var(--danger); background: #f7e8e6; }
.history-empty { margin: 10px 7px; }

.chat-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: #fff; }
.chat-header { flex: 0 0 auto; align-items: flex-start; min-height: 72px; padding: 13px 18px 11px; border-bottom: 1px solid var(--border); }
.chat-header h2 { margin: 3px 0 0; font-size: 16px; font-weight: 600; }
.scope-badge { margin: 0; color: var(--text-tertiary); font-size: 10px; }
.chat-header > div > p:last-child { margin: 3px 0 0; color: var(--text-secondary); font-size: 10px; }
.header-actions button { min-height: 27px; padding: 3px 7px; font-size: 10px; }
.chat-notice { flex: 0 0 auto; margin: 7px 18px 0; padding: 7px 9px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-secondary); background: #fafafa; font-size: 10px; }
.chat-notice--error { border-color: #e8c7c3; color: var(--danger); background: #fff9f8; }
.chat-notice--success { color: var(--success); }
.chat-notice--setup { color: #3e506c; }
.chat-notice a { text-decoration: underline; }

.messages { flex: 1 1 auto; min-height: 0; max-height: none; overflow-y: auto; overscroll-behavior: contain; padding: 20px max(20px, calc((100% - 800px) / 2)) 12px; scrollbar-width: thin; scrollbar-color: #c7c9cc transparent; }
.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 8px; background: #c7c9cc; background-clip: padding-box; }
.empty-state { display: grid; gap: 7px; max-width: 500px; margin: clamp(44px, 9vh, 84px) auto; color: var(--text-tertiary); text-align: center; }
.empty-state strong { color: var(--text); font-size: 15px; font-weight: 600; }
.empty-state span { color: var(--text-secondary); font-size: 12px; }
.empty-state small { font-size: 10px; }
.message-row { display: flex; align-items: flex-start; margin: 0 auto 20px; }
.message-row--user { justify-content: flex-end; }
.message-avatar, .message-meta { display: none; }
.message-body { width: min(100%, 760px); min-width: 0; }
.message-row--user .message-body { width: min(82%, 620px); }
.message-bubble { overflow: hidden; color: var(--text); line-height: 1.75; }
.message-row--user .message-bubble { padding: 8px 11px; border-radius: 7px; background: #f1f1f1; }
.message-bubble p { margin: 0; white-space: pre-wrap; word-break: break-word; }
.message-bubble--collapsed { max-height: 186px; mask-image: linear-gradient(to bottom, #000 75%, transparent); }
.response-progress { display: inline-flex; align-items: center; gap: 8px; min-height: 24px; margin-bottom: 7px; color: var(--text-secondary); font-size: 11px; }
.response-progress__dots { display: inline-flex; align-items: center; gap: 3px; }
.response-progress__dots i { width: 4px; height: 4px; border-radius: 50%; background: #668bb7; animation: pulse .8s infinite alternate; }
.response-progress__dots i:nth-child(2) { animation-delay: .2s; }
.response-progress__dots i:nth-child(3) { animation-delay: .4s; }
.response-progress__time { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.text-action { min-height: 24px; margin-top: 3px; padding: 2px 5px; border: 0; color: var(--text-tertiary); background: transparent; font-size: 10px; }
.text-action:hover:not(:disabled) { color: var(--text); background: var(--hover); }

.attribution-box { margin-top: 8px; padding: 8px 9px; border-left: 2px solid #bfc1c4; color: var(--text-secondary); background: #fafafa; font-size: 10px; line-height: 1.6; }
.attribution-box__label { margin-right: 5px; color: var(--text); font-weight: 600; }
.attribution-box code, .citation-list code { color: var(--info); background: #f1f4f8; }
.attribution-box__open { margin: 0; padding: 0 2px; }
.citation-box { clear: both; margin-top: 8px; }
.citation-toggle { display: flex; width: 100%; min-height: 31px; align-items: center; justify-content: space-between; padding: 6px 8px; border-color: var(--border); color: var(--text-secondary); background: #fafafa; font-size: 10px; text-align: left; }
.citation-list { display: grid; gap: 6px; margin: 0; padding: 7px 0 0; list-style: none; }
.citation-list li { display: flex; gap: 6px; }
.citation-list > li > code { height: fit-content; padding: 2px 4px; border-radius: 3px; font-size: 9px; }
.citation-card { display: grid; width: 100%; gap: 2px; min-height: 0; padding: 8px 9px; border-color: var(--border); border-radius: 5px; color: var(--text); background: #fff; text-align: left; }
.citation-card:hover:not(:disabled) { background: #fafafa; }
.citation-card span, .citation-card small { color: var(--text-tertiary); font-size: 9px; }
.citation-card p { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.citation-card small { overflow-wrap: anywhere; }
.message-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; clear: both; }
.response-duration { color: var(--text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }

.followup-card { flex: 0 1 auto; max-height: 178px; margin: 0 18px 7px; padding: 9px 10px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; background: #fafafa; }
.followup-card > div { display: grid; gap: 2px; }
.followup-card strong { font-size: 11px; }
.followup-card small, .followup-card p, .followup-card ol { color: var(--text-secondary); font-size: 10px; }
.followup-card p, .followup-card ol { margin: 6px 0 0; }
.followup-options { padding: 0; list-style: none; }
.followup-options li { margin: 4px 0; }
.followup-options label { display: flex; align-items: flex-start; gap: 6px; cursor: pointer; }
.followup-confirm { display: flex !important; flex-direction: row !important; align-items: center; justify-content: space-between; margin-top: 7px; padding-top: 7px; border-top: 1px solid var(--border); }
.followup-confirm button { min-height: 27px; padding: 3px 7px; font-size: 10px; }
.composer { flex: 0 0 auto; margin: 0 max(16px, calc((100% - 830px) / 2)) 12px; padding: 9px 10px 7px; border: 1px solid #bfc1c4; border-radius: 8px; background: #fff; }
.message-bubble--selectable { user-select: text; }
.composer-quotes { display: grid; gap: 6px; margin-bottom: 8px; }
.composer-quote { position: relative; margin: 0; padding: 7px 58px 7px 10px; border-left: 3px solid #9dbce2; border-radius: 7px; background: #f4f8fd; color: var(--text-secondary); }
.composer-quote__label { color: var(--text-tertiary); font-size: 10px; }
.composer-quote p { display: -webkit-box; margin: 2px 0 0; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 3; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.5; }
.composer-quote button { position: absolute; top: 6px; right: 7px; min-height: 22px; padding: 2px 5px; border: 0; color: var(--text-tertiary); background: transparent; font-size: 10px; }
.selection-quote-action { position: fixed; z-index: 10000; display: flex; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid #dce4ee; border-radius: 9px; background: #fff; box-shadow: 0 5px 18px rgba(25, 40, 62, .16); color: var(--text-secondary); font-size: 11px; }
.selection-quote-action button { min-height: 27px; padding: 4px 8px; border: 0; border-radius: 6px; background: #edf4fd; color: #31577f; font-size: 11px; }
.composer-suggestions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 8px; padding: 0 0 9px; border-bottom: 1px solid var(--border); }
.composer-suggestions button { min-height: 29px; padding: 4px 9px; border: 1px solid #d7e4f3; border-radius: 8px; color: #355477; background: #f6faff; font-size: 11px; white-space: nowrap; }
.composer-suggestions button:hover:not(:disabled) { background: #eaf3ff; }
.composer-suggestions button:disabled { opacity: .5; }
.composer-suggestions .composer-suggestions__skip { margin-left: auto; border-color: transparent; color: var(--text-tertiary); background: transparent; }
.composer:focus-within { border-color: #7b9bc9; box-shadow: 0 0 0 2px rgba(65,105,166,.1); }
.composer textarea { display: block; width: 100%; min-height: 40px; max-height: 126px; padding: 2px; border: 0; outline: 0; resize: none; color: var(--text); background: transparent; box-shadow: none; font: inherit; line-height: 1.55; }
.composer-footer { align-items: center; margin-top: 4px; }
.composer-footer small { color: var(--text-tertiary); font-size: 9px; }
.composer-footer > div { display: flex; gap: 5px; }
.composer-footer button { min-height: 28px; padding: 4px 9px; font-size: 10px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@keyframes pulse { from { opacity: .3; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .response-progress__dots i { animation: none; opacity: .7; } }

@media (max-width: 760px) {
  .chat-workspace { grid-template-columns: 1fr; border: 0; border-radius: 0; }
  .conversation-sidebar { max-height: 142px; padding: 8px 10px 7px; border-right: 0; border-bottom: 1px solid var(--border); }
  .sidebar-hint, .history-label { display: none; }
  .scope-picker { width: min(300px, 100%); margin: 5px 0; }
  .conversation-list { display: flex; overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; }
  .conversation-row { flex: 0 0 150px; }
  .conversation-delete { color: #999; }
  .chat-header { min-height: 62px; padding: 9px 12px; }
  .chat-header > div > p:last-child { display: none; }
  .messages { padding: 14px 12px 9px; }
  .message-row--user .message-body { width: 90%; }
  .followup-card { margin-inline: 10px; }
  .composer { margin: 0 10px 9px; }
}
/* 桌面端历史移入主导航下方；窄屏仍保留页内历史。 */
.chat-workspace { display: flex; border: 0; border-radius: 0; }
.conversation-sidebar { flex: 1; width: 100%; padding: 14px 2px 0; border: 0; background: transparent; }
.sidebar-head { padding: 0 6px; }
.sidebar-head h2 { color: var(--text-secondary); font-size: 11px; }
.scope-picker { display: block; margin: 10px 2px 16px; padding: 0; border: 0; background: transparent; }
.scope-picker .scope-switch { display: flex; width: 100%; min-height: 36px; align-items: center; justify-content: space-between; padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: var(--text); font-size: 11px; text-align: left; }
.scope-switch small { margin-left: 3px; color: var(--text-tertiary); font-size: 10px; }
.scope-picker .scope-switch > span:last-child { color: var(--text-tertiary); font-size: 10px; }
.history-label { margin-bottom: 5px; }
.conversation-list { flex: 1 1 auto; max-height: calc(100dvh - 320px); overflow-y: auto; }
.conversation-item { min-height: 45px; }
.conversation-title { font-size: 12px; }
.chat-main { flex: 1; }
.chat-header { min-height: 80px; padding: 15px 26px; }
.chat-header h2 { font-size: 18px; }
.chat-header > div > p:last-child, .scope-badge { font-size: 12px; }
.messages { padding: 24px max(24px, calc((100% - 1060px) / 2)) 14px; }
.message-body { width: min(100%, 980px); }
.message-row--user .message-body { width: min(82%, 760px); }
.message-bubble { font-size: 15px; line-height: 1.8; }
.empty-state strong { font-size: 18px; }
.empty-state span { font-size: 13px; }
.citation-card p, .attribution-box, .followup-card small, .followup-card p { font-size: 12px; }
.composer { margin: 0 max(20px, calc((100% - 1060px) / 2)) 16px; padding: 12px 14px 9px; }
.composer textarea { min-height: 54px; font-size: 15px; }
.composer-footer small { font-size: 11px; }
.composer-footer button { font-size: 12px; }
@media (max-width: 980px) {
  .chat-workspace { display: grid; grid-template-columns: 210px minmax(0, 1fr); }
  .conversation-sidebar { padding: 12px 8px 8px; border-right: 1px solid var(--border); }
  .conversation-list { max-height: none; }
}
@media (max-width: 760px) {
  .chat-workspace { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }
  .conversation-sidebar { max-height: 150px; padding: 7px 10px; border-right: 0; border-bottom: 1px solid var(--border); }
  .conversation-list { max-height: 48px; overflow-x: auto; overflow-y: hidden; }
  .chat-header { min-height: 60px; padding: 9px 13px; }
  .messages { padding: 15px 13px 9px; }
  .composer { margin: 0 10px 9px; }
}

.conversation-rename { display: grid; flex: 0 0 23px; width: 23px; min-height: 23px; padding: 0; place-items: center; border: 0; border-radius: 7px; color: #657b92; background: transparent; font-size: 14px; }
.conversation-rename:hover:not(:disabled) { color: #2d527b; background: #dceafa; }
.conversation-delete { border-radius: 7px; }
.conversation-row { border-radius: 9px; }
.conversation-row:hover { background: #dfeaf8; }
.conversation-row.selected { background: #d7e7fa; }
.scope-picker .scope-switch { border-radius: 10px; }
.chat-main { border-radius: 16px; background: #fff; }
.chat-header { min-height: 0; padding: 11px 24px; border-bottom: 1px solid #e4ebf4; border-radius: 16px 16px 0 0; background: #fff; }
.chat-source { margin: 0; color: #5f7184; font-size: 12px; }
.message-bubble { padding: 11px 14px; border: 1px solid #e6ebf2; border-radius: 14px; background: #fff; }
.message-row--user .message-bubble { padding: 10px 14px; border-color: #cfe3fa; border-radius: 14px; background: #e8f3ff; }
.citation-toggle, .citation-card, .followup-card, .chat-notice { border-radius: 10px; }
.composer { width: min(760px, calc(100% - 40px)); margin: 0 auto 12px; padding: 8px 11px 7px; border-radius: 13px; }
.followup-card { width: min(760px, calc(100% - 40px)); max-height: min(260px, 35dvh); margin: 0 auto 8px; }
.composer textarea { min-height: 28px; max-height: 96px; font-size: 14px; }
@media (max-width: 760px) {
  .chat-main { border-radius: 14px; }
  .chat-header { min-height: 0; padding: 8px 12px; }
  .composer { width: calc(100% - 20px); margin: 0 10px 9px; }
  .followup-card { width: calc(100% - 20px); margin: 0 10px 8px; }
}

/* 历史会话更易读；桌面操作只在右键菜单里，窄屏用“⋯”打开。 */
.sidebar-head > h2 { font-size: 14px; }
.icon-button { width: 32px; min-height: 32px; }
.scope-picker .scope-switch { min-height: 40px; font-size: 12px; }
.history-label { font-size: 11px; }
.conversation-list { gap: 2px; }
.conversation-row { min-height: 52px; outline-offset: 1px; }
.conversation-row:focus-visible { outline: 2px solid #7da2df; }
.conversation-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; min-height: 51px; gap: 1px 5px; padding: 7px 8px 7px 10px; }
.conversation-title { font-size: 13px; font-weight: 570; }
.conversation-pinned { color: #4e7195; font-size: 10px; }
.conversation-item small { grid-column: 1 / -1; font-size: 10px; }
.conversation-more { display: grid; flex: 0 0 28px; width: 28px; min-height: 28px; margin-right: 3px; padding: 0; place-items: center; border: 0; border-radius: 8px; color: var(--text-secondary); background: transparent; font-size: 18px; }
.conversation-more:hover:not(:disabled) { background: var(--hover); }
.conversation-menu { position: fixed; z-index: 1000; display: grid; width: 178px; padding: 5px; border: 1px solid var(--border-strong); border-radius: 11px; background: #fff; box-shadow: 0 12px 32px rgba(40, 65, 95, .15); }
.conversation-menu button { width: 100%; min-height: 36px; padding: 7px 10px; border: 0; border-radius: 7px; background: transparent; font-size: 12px; font-weight: 450; text-align: left; }
.conversation-menu button:hover { background: #edf4fc; }
.conversation-menu .conversation-menu__danger { color: var(--danger); }
.conversation-menu .conversation-menu__danger:hover { background: #fff1f0; }
@media (max-width: 760px) {
  .conversation-row { flex: 0 0 176px; }
  .conversation-item { min-height: 48px; }
}
</style>
