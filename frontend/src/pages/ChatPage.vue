<script setup lang="ts">
import StudyMascot from '../components/StudyMascot.vue';
import {notifyPracticeRequestsChanged} from '../lib/practiceRequestChanges';
import { assistantTerminal, type AssistantStatus } from '../lib/assistantTerminal';
import { restoreComposerDraft } from '../lib/composerDraft';
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "../api/client";
import {
  createChatSession,
  cancelGenerationConfirmation,
  createDeepQA,
  deleteChatSession,
  fetchChatMessages,
  listChatSessions,
  renameChatSession,
  streamChatAnswer,
  type ChatMessage,
  type ChatMode,
  type ChatSession,
  type MatchedKp,
  type Citation,
  type AssistanceAction,
} from "../api/chat";
import { studyContextFromRoute, assistantConversationLink, rememberAssistantConversation } from "../lib/studyContext";
import PracticeRequestCard from "../components/PracticeRequestCard.vue";
import PersonalQuestionResult from "../components/PersonalQuestionResult.vue";
import GenerationFailureNotice from '../components/GenerationFailureNotice.vue';
import PersonalGenerationConfirmation from "../components/PersonalGenerationConfirmation.vue";
import type { LearningTask } from "../api/learningTasks";
import { countReadyMaterials } from "../api/materials";
import { transcribeQuestionImage } from "../api/vision";
import { generatePersonalQuestions, type GenerationResult } from "../api/personalQuestions";
import { fetchKnowledgeTree } from "../api/study";
import type { KnowledgeNodeView } from "../types/practice";
import { photoFileError } from "../lib/photoInput";
import { useAsyncTask } from "../composables/useAsyncTask";
import MarkdownContent from "../components/MarkdownContent.vue";
import AppIcon from "../components/AppIcon.vue";
import { chatAnswerText } from "../lib/chatAnswerText";
import { readDeepQADraft, removeDeepQADraft } from "../lib/deepQADraft";
import { assistantFailureMessage, assistantTurnFromHistory, createAssistantTurn, retryAssistantTurn, savedAssistantTurn, type AssistantTurn } from "../lib/assistantTurn";
import { resolveGenerationConfirmationReply } from "../lib/generationConfirmationReply";

defineOptions({ name: "ChatPage" });
const props=withDefaults(defineProps<{privateMode?:boolean}>(),{privateMode:false});
const privateScopeIds=computed(()=>{
  const value=typeof route.query.material_ids==='string'?route.query.material_ids:typeof route.query.material_id==='string'?route.query.material_id:'';
  return value.split(',').filter(v=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v)).slice(0,8);
});

const sessionId = ref<string | null>(null);
const sessions = ref<ChatSession[]>([]);
const messages = ref<ChatMessage[]>([]);
const question = ref("");
// 普通问答的图片题入口：只做临时转写，识别文本由用户核对后再发送。
const questionImageInput = ref<HTMLInputElement | null>(null);
const questionImageBusy = ref(false);
const questionImageNotice = ref<string | null>(null);
const questionImageError = ref<string | null>(null);
const questionImageController = ref<AbortController | null>(null);
// 图片识别 → 个人变式练习；模式必须由用户显式选择或确认降级。
const variantOpen = ref(false);
const variantKps = ref<Array<{ id: string; name: string }>>([]);
const variantKpsLoading = ref(false);
const variantKpId = ref("");
const variantCount = ref(1);
const variantDifficulty = ref<"basic" | "improved" | "comprehensive">("basic");
const variantType = ref<"single_choice" | "fill_blank" | "calculation" | "proof" | "subjective">("single_choice");
const variantMode = ref<"ai_enhanced" | "ai_generated">("ai_enhanced");
const variantBusy = ref(false);
const variantError = ref<string | null>(null);
const variantNeedsFallback = ref(false);
const variantResult = ref<GenerationResult | null>(null);
function pickQuestionImage() {
  questionImageError.value = null;
  questionImageInput.value?.click();
}
async function onQuestionImage(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file || questionImageBusy.value) return;
  const invalid = photoFileError(file);
  if (invalid) { questionImageError.value = invalid; return; }
  questionImageBusy.value = true;
  questionImageError.value = null;
  questionImageNotice.value = null;
  const controller = new AbortController();
  questionImageController.value = controller;
  try {
    const result = await transcribeQuestionImage(file, controller.signal);
    const text = (result.text || "").trim();
    if (!text) { questionImageError.value = "图片里没有识别到可用文字，请换一张更清晰的图片。"; return; }
    question.value = question.value.trim() ? question.value.trimEnd() + "\n\n" + text : text;
    questionImageNotice.value = "已识别图片中的题目文字，请核对后发送；图片不会保存。";
    await nextTick();
  } catch (error) {
    questionImageError.value = error instanceof ApiError ? error.message : "图片识别失败，请换一张图片或改用文字输入。";
  } finally {
    if (questionImageController.value === controller) questionImageController.value = null;
    questionImageBusy.value = false;
  }
}

function flattenVariantNodes(nodes: KnowledgeNodeView[]): Array<{ id: string; name: string }> {
  const output: Array<{ id: string; name: string }> = [];
  for (const node of nodes) {
    if (node.is_assessable && !node.is_reference_only && !(node.children?.length)) output.push({ id: node.id, name: node.name });
    if (node.children?.length) output.push(...flattenVariantNodes(node.children));
  }
  return output;
}

async function openVariantPanel(): Promise<void> {
  variantOpen.value = true;
  variantError.value = null;
  variantResult.value = null;
  variantNeedsFallback.value = false;
  if (variantKps.value.length) return;
  variantKpsLoading.value = true;
  try {
    const tree = await fetchKnowledgeTree();
    variantKps.value = flattenVariantNodes(tree.nodes);
  } catch {
    variantError.value = "无法加载知识点，请稍后重试。";
  } finally {
    variantKpsLoading.value = false;
  }
}

function closeVariantPanel(): void {
  if (variantBusy.value) return;
  variantOpen.value = false;
}

async function submitVariant(): Promise<void> {
  const text = question.value.trim();
  if (!text) { variantError.value = "请先识别或输入题目文字。"; return; }
  if (!variantKpId.value) { variantError.value = "请选择知识点。"; return; }
  variantBusy.value = true;
  variantError.value = null;
  variantNeedsFallback.value = false;
  try {
    const result = await generatePersonalQuestions({
      request_key: crypto.randomUUID(),
      generation_mode: variantMode.value,
      targets: [{ kp_id: variantKpId.value, question_type: variantType.value, count: variantCount.value, difficulty: variantDifficulty.value }],
      reference_text: text,
      reference_source: { type: "image_transcription" },
      user_requirement: "基于图片题目生成个人变式练习，不照抄原题，不给答案。",
    });
    variantResult.value = result;
    if (!result.question_ids.length) variantError.value = result.message || "本次没有生成可用题目。";
  } catch (error) {
    variantError.value = error instanceof ApiError ? error.message : "生成变式练习失败，请稍后重试。";
    variantNeedsFallback.value = error instanceof ApiError
      && error.code === "personal_generation_unsupported" && variantMode.value === "ai_enhanced";
  } finally {
    variantBusy.value = false;
  }
}

async function fallbackVariant(): Promise<void> {
  variantMode.value = "ai_generated";
  await submitVariant();
}
const pendingDeepQA = ref<ReturnType<typeof readDeepQADraft>>(null);
const learningContext = computed(() => props.privateMode?{surface:'materials' as const,origin:'material' as const,
  material_id:privateScopeIds.value.length===1?privateScopeIds.value[0]:undefined}:pendingDeepQA.value
    ? {...pendingDeepQA.value.context,conversation_id:undefined,task_id:undefined,surface:'chat' as const}
    :studyContextFromRoute(route.query));
const requestedAction = ref<AssistanceAction>("auto");
const turnRequests = new Map<string, AssistantTurn>();
const uncertainTurn = ref<AssistantTurn | null>(null);
const uncertainCanRetry = ref(false);
const retryChecking = ref(false);
const quotedAnswers = ref<Array<{ id: string; text: string }>>([]);
const answerSelection = ref<{ text: string; left: number; top: number } | null>(null);
// 统一状态（阶段 E）：页面的「加载中 / 失败」这一对状态由 pageTask 承载，
// 页面不再自己维护 loading 布尔 + 一个 error 字符串。
// `error` 与 `loading` 仍作为模板绑定的名字保留（testid 与文案契约不变）。
const pageTask = useAsyncTask<void>(null, {
  fallbackMessage: "无法加载问答页面",
});
const loading = computed(() => pageTask.state.value === "loading");
// 首次挂载时，按钮已进入 DOM 但页面初始化请求可能尚未开始；
// 在初始化完成前禁止切换，避免早期点击被 onMounted 的默认会话模式覆盖。
const pageInitialized = ref(false);
// `error` 仍由页面持有：它的文案要按业务分支细分（新建会话失败、改名失败、
// 删除失败、追练追加失败、上游未配置…），不适合塞进一个统一映射表。
// 页面加载失败这一种情况由 pageTask.state==='error' 决定，见 onMounted。
const error = ref("");
// `sending` 保留为页面自身的业务状态：它是**一次 SSE 流的过程标志**，
// 由流内多个分支（错误帧、断连、取消）决定何时复位，
// 与「一次请求的 submitting」不是同一个语义，硬套 submit() 反而会藏掉流的状态。
const sending = ref(false);
type StreamStage = "retrieving" | "generating" | "streaming" | "recovering";
const streamStage = ref<StreamStage>("retrieving");
const activeStreamMessageId = ref<string | null>(null);
const streamElapsedSeconds = ref(0);
const streamStageLabel = computed(() => {
  if (streamStage.value === "retrieving") return "正在准备回答…";
  if (streamStage.value === "generating") return "正在组织回答…";
  if (streamStage.value === "recovering") return "正在自动恢复完整回答…";
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
const selectedMode = ref<ChatMode>(props.privateMode?"user":"builtin");
const compactSidebar = ref(typeof window !== "undefined" && window.matchMedia("(max-width: 980px)").matches);
const updateSidebarMode = () => { compactSidebar.value = window.matchMedia("(max-width: 980px)").matches; };
const readyByMode = ref<Record<ChatMode, number>>({ user: 0, builtin: 0 });
const materialErrors = reactive<Record<ChatMode, string>>({ user: '', builtin: '' });
const materialsLoading = reactive<Record<ChatMode, boolean>>({ user: false, builtin: false });
const sessionsError = ref('');
const messagesError = ref('');
const scrollBox = ref<HTMLElement | null>(null);
const expandedMessageIds = ref(new Set<string>());
const feedbackNotice = ref("");
let controller: AbortController | null = null;
const router = useRouter();
const route = useRoute();
const chatPurpose = () => props.privateMode ? 'materials' as const : 'qa' as const;

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
const canSend = computed(() => Boolean((question.value.trim() || quotedAnswers.value.length) && !sending.value && !loading.value && (!props.privateMode||privateScopeIds.value.length)));

function modeLabel(mode: ChatMode): string {
  return mode === "user" ? "资料问答" : "学习问答";
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
function dismissSelectionAction(): void {
  // 引用浮层按选中时的位置定位；滚动后主动收起，避免它漂离所选文本。
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
  // 集合记录用户主动折叠的回答；教学正文默认完整显示，历史也一致。
  return !expandedMessageIds.value.has(messageId);
}
function toggleExpanded(messageId: string): void {
  const next = new Set(expandedMessageIds.value);
  next.has(messageId) ? next.delete(messageId) : next.add(messageId);
  expandedMessageIds.value = next;
}
async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight;
}

async function refreshMaterial(mode: ChatMode): Promise<void> {
  if (materialsLoading[mode]) return;
  materialsLoading[mode] = true;
  materialErrors[mode] = '';
  try { readyByMode.value[mode] = await countReadyMaterials(mode); }
  catch (caught) {
    console.warn('chat material readiness failed', mode, caught);
    materialErrors[mode] = `${mode === 'user' ? '用户' : '内置'}资料列表加载失败，不影响查看已有聊天记录。`;
  } finally { materialsLoading[mode] = false; }
}
async function refreshMaterials(): Promise<void> {
  await Promise.all([refreshMaterial('user'), refreshMaterial('builtin')]);
}
/**
 * 取历史会话。
 *
 * 必须**按当前范围过滤**：篇 01 规定两种问答模式严格隔离（检索范围、matched_kp、
 * 追练推荐、学习事件都不同），混在一个列表里用户分不清哪条属于哪个范围。
 * 后端同时不再返回没有任何消息的空会话，所以列表里每一条都能点开看。
 */
async function refreshSessions(): Promise<void> {
  sessionsError.value = '';
  try { sessions.value = await listChatSessions(selectedMode.value,props.privateMode ? undefined : 'qa'); }
  catch (caught) {
    console.warn('chat session list failed', caught);
    sessionsError.value = '会话列表暂时无法加载，请重试。';
  }
}
let sessionLoadVersion = 0;
const sessionLoading = ref(false);
async function openSession(session: ChatSession): Promise<void> {
  if (sending.value) return;
  if(!props.privateMode&&session.mode==='user'){await router.push({path:'/materials/qa',query:{session_id:session.session_id}});return;}
  if(props.privateMode&&session.mode!=='user')return;
  const version = ++sessionLoadVersion;
  sessionLoading.value = true;
  messagesError.value = '';
  error.value = "";
  feedbackNotice.value = "";
  clearQuotedAnswerContext();
  sessionId.value = session.session_id;
  selectedMode.value = session.mode;
  if(props.privateMode) await router.replace({path:'/materials/qa',query:{session_id:session.session_id,
    ...(session.material_scope_ids?.length?{material_ids:session.material_scope_ids.join(',')}:{})}});
  messages.value = [];
  try {
    const items = await fetchChatMessages(session.session_id, chatPurpose());
    if (version !== sessionLoadVersion || sessionId.value !== session.session_id) return;
    messages.value = items;
    if (!props.privateMode) {
      const location = studyContextFromRoute(route.query);
      const hasLocation = Boolean(location.question_id || location.practice_item_id || location.attempt_id
        || location.material_id || location.chunk_id || location.task_id || location.knowledge_node_ids?.length);
      const explicitTarget = route.query.session_id === session.session_id;
      if (!explicitTarget || (!hasLocation && route.query.clear_context !== "1")) {
        const saved = [...items].reverse().find(message => message.status === "completed" && message.study_context)?.study_context;
        if (saved) await router.replace(assistantConversationLink(session.session_id, {
          ...saved, conversation_id: session.session_id, task_id: undefined, surface: "chat", origin: "conversation",
        }));
      }
    }
  } catch (caught) {
    console.warn('chat messages failed', session.session_id, caught);
    if (version === sessionLoadVersion) messagesError.value = '会话消息暂时无法加载，请重试。';
    return;
  } finally {
    if (version === sessionLoadVersion) sessionLoading.value = false;
  }
  if (route.query.session_id && route.query.session_id !== session.session_id) await router.replace({ path: "/chat" });
  await scrollToBottom();
}

async function syncRouteSession(): Promise<void> {
  if (!(route.path.startsWith("/chat")||props.privateMode) || loading.value) return;
  const requestedId = typeof route.query.session_id === "string" ? route.query.session_id : null;
  if (!requestedId || requestedId === sessionId.value || sending.value) return;
  try {
    const allSessions = await listChatSessions(undefined,props.privateMode ? undefined : 'qa');
    if (route.query.session_id !== requestedId || sending.value) return;
    const target = allSessions.find((item) => item.session_id === requestedId);
    if (!target) {
      error.value = "分享的会话不存在或已删除";
      return;
    }
    if(target.mode!==(props.privateMode?'user':'builtin')){await openSession(target);return;}
    selectedMode.value = target.mode;
    sessions.value = allSessions.filter((item) => item.mode === target.mode);
    await openSession(target);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "无法读取分享的会话，请稍后重试";
  }
}
/**
 * 开一段**尚未落库**的新对话。
 *
 * 为什么不在这里建会话：见 `changeScope` 的说明。会话统一推迟到
 * `send()` 里「用户真的发出第一条问题」时才创建。
 */
function startDraft(preserveHandoff = false): void {
  if (sending.value) return;
  ++sessionLoadVersion;
  sessionLoading.value = false;
  error.value = "";
  feedbackNotice.value = "";
  clearQuotedAnswerContext();
  sessionId.value = null;
  messages.value = [];
  if (!preserveHandoff) {
    pendingDeepQA.value = null;
    if (route.query.study_draft) void router.replace({ path: "/chat" });
  }
  if (route.query.session_id) void router.replace({ path: props.privateMode?"/materials/qa":"/chat",query:props.privateMode?{material_ids:privateScopeIds.value.join(',')}:{} });
  requestedAction.value = "auto";
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
  if (sending.value || loading.value || !pageInitialized.value) return;
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
    const updated = await renameChatSession(target.session_id, title, chatPurpose());
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
    await deleteChatSession(target.session_id, chatPurpose());
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

const invalidGenerationCards = new Set<string>();
async function confirmGeneration(message: ChatMessage, kpId: string): Promise<void> {
  if (sending.value || !message.personal_generation_confirmation) return;
  await send(kpId, message);
}
async function confirmGenerationTargets(message: ChatMessage, targets: NonNullable<NonNullable<ChatMessage['personal_generation_confirmation']>['proposed_targets']>): Promise<void> {
  if (sending.value || !message.personal_generation_confirmation) return;
  await send(undefined, message, undefined,
    targets.map(({kp_id,question_type,count,difficulty})=>({kp_id,question_type,count,difficulty})));
}
function onGenerationNodeSelection(message: ChatMessage, kpId: string | null): void {
  const confirmation = message.personal_generation_confirmation;
  if (!confirmation) return;
  message.personal_generation_confirmation = { ...confirmation, selected_kp_id: kpId };
  error.value = "";
}
async function cancelGeneration(message: ChatMessage): Promise<void> {
  if (sending.value || !sessionId.value) return;
  sending.value = true;
  try { await cancelGenerationConfirmation(sessionId.value, message.message_id, chatPurpose()); message.personal_generation_confirmation = null; error.value = ''; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '暂时无法取消，请稍后重试。'; }
  finally { sending.value = false; }
}
async function send(confirmedKpId?: string, confirmation?: ChatMessage, existingTurn?: AssistantTurn,
  confirmedTargets?: Array<{kp_id:string;question_type:string;count:number;difficulty:string}>): Promise<void> {
  // Enter 与按钮使用相同的就绪边界。否则初始化异步返回的 startDraft()
  // 会清空已通过 Enter 发出的消息，后端明明存了确认卡，页面却是空白。
  if (sessionLoading.value || loading.value || !pageInitialized.value) {
    error.value = "正在读取会话，请稍后发送。输入内容已保留。";
    return;
  }
  if (sending.value || (!existingTurn && !confirmation && !question.value.trim() && !quotedAnswers.value.length)) return;
  const latestAssistant = [...messages.value].reverse().find((item) => item.role === "assistant");
  if (!existingTurn && !confirmation && latestAssistant?.personal_generation_confirmation) {
    const reply = resolveGenerationConfirmationReply(question.value, latestAssistant.personal_generation_confirmation);
    if (reply.kind === "confirm") {
      question.value = "";
      error.value = "";
      await send(reply.kpId, latestAssistant);
      return;
    }
    if (reply.kind === "confirm-targets") {
      question.value = "";
      error.value = "";
      await send(undefined, latestAssistant, undefined,
        reply.targets.map(({kp_id,question_type,count,difficulty})=>({kp_id,question_type,count,difficulty})));
      return;
    }
    if (reply.kind === "needs-node") {
      error.value = "请先在出题卡中选择知识点，或直接回复“确定 + 完整知识点名称”。输入内容已保留。";
      return;
    }
    if (reply.kind === 'unmatched-node') {
      error.value = `未找到知识点「${reply.requested}」。请从出题卡选择现有节点，或取消；没有生成题目。输入已保留。`;
      return;
    }
  }
  const quoteContext = (existingTurn || confirmation ? [] : quotedAnswers.value).map((item) =>
    "引用的回答片段：\n" + item.text.split("\n").map((line) => "> " + line).join("\n"),
  ).join("\n\n");
  const text = existingTurn?.question ?? confirmation?.personal_generation_confirmation?.question ?? [quoteContext, question.value.trim()].filter(Boolean).join("\n\n");
  if (Array.from(text).length > 4000) {
    error.value = "问题与引用合计不能超过 4000 字，请缩短问题或移除部分引用。输入内容已保留。";
    return;
  }
  const draft = question.value;
  const draftQuotes = [...quotedAnswers.value];
  let accepted = false;
  let rejectedBeforeAcceptance = false;
  error.value = "";
  feedbackNotice.value = "";
  sending.value = true;
  // 新对话在这里才落库：只有用户真的发出第一条问题，才值得在历史里占一条。
  // 之前是「点新建/切范围就建」，导致库里一半会话是没有任何消息的空壳。
  let id = sessionId.value;
  if (id === null) {
    try {
      if (pendingDeepQA.value && !props.privateMode) {
        const draft = pendingDeepQA.value;
        const sourceId = draft.sourceSessionId ?? (await createChatSession("今日学习", "builtin", { purpose: "study" })).session_id;
        // 只有实际发送问题时才把学习交接和问答会话落库。
        draft.sourceSessionId = sourceId;
        const response = await createDeepQA(sourceId, { ...draft.context, conversation_id: sourceId }, text, draft.requestKey);
        id = response.session_id;
        messages.value = await fetchChatMessages(id, 'qa');
        removeDeepQADraft(draft.requestKey);
        pendingDeepQA.value = null;
        await router.replace(assistantConversationLink(id, response.study_context));
      } else {
        const created = await createChatSession("新对话", selectedMode.value,{purpose:props.privateMode?'materials':'qa',material_scope_ids:props.privateMode?privateScopeIds.value:[]});
        id = created.session_id;
      }
      sessionId.value = id;
    } catch (caught) {
      sending.value = false;
      // 输入框内容保留：创建失败时用户可以直接再发一次，不用重打问题。
      error.value = caught instanceof ApiError ? caught.message : "无法新建会话，请重试";
      return;
    }
  }
  if (!existingTurn && !confirmation) { question.value = ""; clearQuotedAnswerContext(); }
  const action = existingTurn?.options.qa_action ?? (confirmation ? 'auto' : requestedAction.value);
  const latestTask = [...messages.value].reverse().find(m => m.planner_task_id)?.planner_task_id;
  const context = existingTurn?.options.study_context ?? { ...learningContext.value, conversation_id: id, task_id: latestTask ?? undefined };
  const request = existingTurn ?? createAssistantTurn(id, text, { assistant: true, purpose: chatPurpose(), study_context: context,
    qa_action: action, personal_generation_confirmed_kp_id: confirmedKpId,
    personal_generation_confirmed_targets: confirmedTargets,
    personal_generation_confirmation_message_id: confirmation?.message_id }, messages.value);
  uncertainTurn.value = null;
  uncertainCanRetry.value = false;
  if (selectedMode.value === "builtin") rememberAssistantConversation(id);
  const localUserId = `local-user-${Date.now()}`;
  const localAssistantId = `streaming-${Date.now()}`;
  if (!existingTurn && !confirmation) messages.value.push({ message_id: localUserId, role: "user", content: text, status: "completed", matched_kp_id: null, citations: [] });
  const assistant = reactive<ChatMessage>({ message_id: existingTurn?.replyId ?? localAssistantId, role: "assistant", content: "", status: "generating", matched_kp_id: null, citations: [] });
  const previousReplyIndex = existingTurn?.replyId ? messages.value.findIndex(message => message.message_id === existingTurn.replyId) : -1;
  if (previousReplyIndex >= 0) messages.value[previousReplyIndex] = assistant;
  else messages.value.push(assistant);
  activeStreamMessageId.value = assistant.message_id;
  streamStage.value = "retrieving";
  startStreamTimer();
  controller = new AbortController();
  await scrollToBottom();
  let wireStatus: AssistantStatus = 'generating';
  try {
    await streamChatAnswer(id, text, async (event, data) => {
      if (wireStatus !== 'generating') return;
      wireStatus = assistantTerminal(wireStatus, event, data);
      if (event === "meta") {
        accepted = true;
        assistant.message_id = String(data.message_id);
        request.replyId = assistant.message_id;
        activeStreamMessageId.value = assistant.message_id;
        streamStage.value = "generating";
      }
      if (event === "delta") {
        streamStage.value = data.recovering === true ? "recovering" : "streaming";
        if (data.replace === true) assistant.content = String(data.text ?? "");
        else assistant.content += String(data.text ?? "");
        await scrollToBottom();
      }
      if (event === "citations") {
        assistant.citations = (data.citations as Citation[] | undefined) ?? [];
      }
      if (event === "planner") assistant.planner_task_id = String(data.task_id);
      if (event === "practice_request") assistant.practice_request_id = String(data.id);
      if (event === 'personal_generation') assistant.personal_generation=data as unknown as ChatMessage['personal_generation'];
      if (event === 'personal_training') assistant.personal_training=data as unknown as ChatMessage['personal_training'];
      if (event === 'personal_generation_confirmation') assistant.personal_generation_confirmation=data as unknown as ChatMessage['personal_generation_confirmation'];
      if (event === "web_sources") assistant.web_sources = data.sources as ChatMessage['web_sources'];
      if (event === "information_source") assistant.qa_information_route = String(data.source);
      if (event === "done") {
        notifyPracticeRequestsChanged();
        assistant.status = wireStatus;
        if (wireStatus === 'failed') {
          assistant.assistant_error_code = String(data.code ?? '');
          assistant.retryable = data.retryable !== false;
          error.value = assistantFailureMessage(assistant.assistant_error_code);
        } else if (wireStatus === 'completed') error.value = '';
        if (typeof data.answer === "string") assistant.content = data.answer;
        assistant.answer_source = (data.answer_source as ChatMessage["answer_source"]) ?? null;
        assistant.response_duration_ms = typeof data.response_duration_ms === "number" ? data.response_duration_ms : null;
        assistant.matched_kp_id = data.matched_kp_id ? String(data.matched_kp_id) : null;
        // 归因依据由后端给出并落库，前端只负责显示，不自己算。
        assistant.matched_kp = (data.matched_kp as MatchedKp | null | undefined) ?? null;
        assistant.citations = (data.citations as Citation[] | undefined) ?? assistant.citations;
      }
      if (event === "error") {
        if (data.code === 'personal_generation_confirmation_invalid' && confirmation) {
          invalidGenerationCards.add(confirmation.message_id);
          rejectedBeforeAcceptance = true;
          question.value = restoreComposerDraft(question.value, text);
          uncertainTurn.value = null;
        }
        if(data.message_id){accepted=true;assistant.message_id=String(data.message_id);request.replyId=assistant.message_id;}
        assistant.status = "failed";
        assistant.assistant_error_code = String(data.code ?? '');
        assistant.retryable = data.retryable !== false;
        // 规格 2.5：llm_not_configured → 明确「尚未配置问答模型」并给出配置指引；
        // generation_failed / retrieval_failed → 该条消息标记失败，只提供普通重试。
        const code = String(data.code ?? "");
        error.value =
          code === "llm_not_configured"
            ? "尚未配置问答模型：请打开左下角设置，填写并保存模型配置。"
            : code === "answer_truncated"
              ? "自动恢复后仍达到模型输出上限。已保留未完成内容，请检查设置中的模型与输出预算后重试。"
            : code === "retrieval_timeout"
              ? "资料检索超过 30 秒，已停止本次请求。请确认资料已完成索引，或缩小问题范围后重试。"
            : code === "retrieval_failed"
              ? "检索暂时失败（向量库或模型不可用），可以稍后重试这次提问。"
              : assistantFailureMessage(code, String(data.message ?? "回答生成失败"));
      }
    }, controller.signal, request.options);
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
        if (caught.code === 'personal_generation_confirmation_invalid' && confirmation) {
          invalidGenerationCards.add(confirmation.message_id);
          question.value = restoreComposerDraft(question.value, text);
          uncertainTurn.value = null;
        }
        rejectedBeforeAcceptance = !accepted && caught.status !== null;
        error.value =
          caught.code === "llm_not_configured"
            ? "尚未配置问答模型：请打开左下角设置，填写并保存模型配置。"
            : caught.code === "answer_truncated"
              ? "自动恢复后仍达到模型输出上限。已保留未完成内容，请检查设置中的模型与输出预算后重试。"
            : caught.code === "retrieval_timeout"
              ? "资料检索超过 30 秒，已停止本次请求。请确认资料已完成索引，或缩小问题范围后重试。"
            : assistantFailureMessage(caught.code, caught.message);
      } else {
        error.value = "无法连接问答服务";
      }
    }
  } finally {
    if (rejectedBeforeAcceptance && !confirmation && !existingTurn && !question.value && !quotedAnswers.value.length) {
      question.value = draft;
      quotedAnswers.value = draftQuotes;
    }
    if (assistant.status === "completed") requestedAction.value = "auto";
    activeStreamMessageId.value = null;
    stopStreamTimer();
    controller = null;
    await refreshSessions().catch(() => undefined);
    if (request.replyId) turnRequests.set(request.replyId, request);
    // Read after a disconnected stream before offering any resend. A successful
    // server response may have been saved even when its terminal frame was lost.
    let restored: ChatMessage[] | null = null;
    await fetchChatMessages(id, chatPurpose()).then((items) => {
      for (const item of items) if (invalidGenerationCards.has(item.message_id)) item.personal_generation_confirmation = null;
      restored = items; if (sessionId.value === id) messages.value = items;
    }).catch(() => undefined);
    const saved = restored ? savedAssistantTurn(request, restored) : undefined;
    if (saved) turnRequests.set(saved.message_id, { ...request, replyId: saved.message_id });
    if (saved?.status === 'completed') error.value = '';
    else if (assistant.status === 'failed' && !rejectedBeforeAcceptance && saved?.status !== 'failed') {
      uncertainTurn.value = request;
      error.value = saved?.status === 'generating' ? '连接已中断，这条请求仍在处理；请读取状态。' : `${error.value} 原提问已保留，请先读取状态再重试。`;
    }
    await scrollToBottom();
    sending.value = false;
  }
}
function cancel(): void {
  controller?.abort();
}
async function askLearningAction(action: AssistanceAction): Promise<void> {
  requestedAction.value = action;
  question.value = ({ hint_1: "给我一点提示，不要告诉答案", hint_2: "请提示下一步，不要给最终结果", solution: "请讲解当前题的完整参考解答", process_review: "请辅助检查我这道题的作答过程；缺少步骤时先问我" } as Record<string,string>)[action];
  await send();
}
async function retryLearningMessage(message: ChatMessage) {
  if (!sessionId.value || sending.value || retryChecking.value || message.retryable === false) return;
  const original = turnRequests.get(message.message_id) ?? assistantTurnFromHistory(sessionId.value, message, messages.value);
  if (!original) { error.value = '无法恢复原提问，请重新提出问题。'; return; }
  let retry: AssistantTurn | undefined;
  retryChecking.value = true;
  try {
    const history = await fetchChatMessages(original.sessionId, chatPurpose());
    const saved = savedAssistantTurn(original, history);
    if (sessionId.value === original.sessionId) messages.value = history;
    if (saved?.status === 'completed' || saved?.status === 'cancelled') { error.value = ''; return; }
    if (saved?.status === 'generating') { uncertainTurn.value = original; error.value = '这条请求仍在处理，请稍后读取状态；不会重复发送。'; return; }
    if (saved?.retryable === false) { error.value = '该请求已结束，可编辑原提问后再明确发送新请求。'; return; }
    retry = retryAssistantTurn(original, saved);
  } catch { uncertainTurn.value = original; error.value = '暂时无法确认原请求状态，已保留提问；请先读取状态。'; }
  finally { retryChecking.value = false; }
  if (retry) await send(undefined, undefined, retry);
}
function editFailedMessage(message: ChatMessage) {
  if (!sessionId.value || sending.value) return;
  if (question.value.trim() || quotedAnswers.value.length) { error.value = '输入框已有新的草稿，请先保留或发送该草稿，再编辑原提问。'; return; }
  const original = turnRequests.get(message.message_id) ?? assistantTurnFromHistory(sessionId.value, message, messages.value);
  if (!original) { error.value = '无法恢复原提问，请重新输入。'; return; }
  question.value = original.question;
  requestedAction.value = 'auto';
  error.value = '原提问已放入输入框。修改后发送会开始一次新的请求。';
}
async function recoverUncertainTurn() {
  const original = uncertainTurn.value;
  if (!original || sending.value || retryChecking.value) return;
  if (uncertainCanRetry.value) { await send(undefined, undefined, original); return; }
  retryChecking.value = true;
  try {
    const history = await fetchChatMessages(original.sessionId, chatPurpose());
    const saved = savedAssistantTurn(original, history);
    if (sessionId.value === original.sessionId) messages.value = history;
    if (saved?.status === 'completed' || saved?.status === 'cancelled') { uncertainTurn.value = null; error.value = ''; return; }
    if (saved?.status === 'generating') { error.value = '这条请求仍在处理，请稍后读取状态；不会重复发送。'; return; }
    if (saved?.status === 'failed') { turnRequests.set(saved.message_id, retryAssistantTurn(original, saved)); uncertainTurn.value = null; error.value = '原回复未完成，可点击该回复下的重试按钮。'; return; }
    uncertainCanRetry.value = true;
    error.value = '未读取到已保存的回复，可使用原请求重试。';
  } catch { error.value = '暂时无法确认原请求状态，已保留提问；请先读取状态。'; }
  finally { retryChecking.value = false; }
}
async function initializeConversations() {
  try {
    await pageTask.run(async () => {
      // 先不带 mode 取一次历史：**最近用过的那条会话的模式**就是用户上次待的地方，
      // 用它作为默认范围。这样刷新页面会回到原处，而不是每次跳回另一个范围。
      const recent = await listChatSessions(undefined,props.privateMode ? undefined : 'qa');
      const fallback: ChatMode = props.privateMode?"user":"builtin";
      const sharedId = typeof route.query.session_id === "string" ? route.query.session_id : null;
      pendingDeepQA.value = props.privateMode ? null : readDeepQADraft(route.query.study_draft);
      const nodeEntry = !props.privateMode && studyContextFromRoute(route.query).knowledge_node_ids?.length;
      const initial = sharedId ? recent.find((item) => item.session_id === sharedId) : pendingDeepQA.value||nodeEntry||props.privateMode&&privateScopeIds.value.length?undefined:recent.find(item=>item.mode===fallback);
      selectedMode.value = fallback;
      await refreshSessions();
      // 分享链接优先打开指定会话；普通访问仍回到最近使用的会话。
      if (initial) await openSession(initial);
      else startDraft(Boolean(pendingDeepQA.value));
      if (pendingDeepQA.value) question.value = pendingDeepQA.value.problem;
      if (sharedId && !initial) error.value = "分享的会话不存在或已删除";
    });
    // 页面级加载失败：把统一状态给出的文案（含非 ApiError 的兜底）接到页面提示上。
    if (pageTask.state.value === "error") sessionsError.value = '会话列表暂时无法加载，请重试。';
  } finally {
    pageInitialized.value = true;
  }
}
onMounted(() => { void refreshMaterials(); void initializeConversations(); });
onMounted(() => {
  loadPinnedSessions();
  window.addEventListener("resize", updateSidebarMode);
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("pointerdown", onSelectionPointerDown);
  window.addEventListener("scroll", dismissSelectionAction, true);
  window.addEventListener("keydown", onContextMenuEscape);
});
watch(() => route.query.session_id, () => { void syncRouteSession(); });
// 从知识树切换节点时开未落库的草稿，不恢复另一节点的旧确认卡。
watch(()=>route.query.knowledge_node_id,(id,previous)=>{
  if(id!==previous && id && route.path==='/chat' && !route.query.session_id && pageInitialized.value && !props.privateMode)startDraft();
});
watch(() => route.query.study_draft, (id) => {
  const draft = readDeepQADraft(id);
  if (!draft || props.privateMode || sending.value) return;
  startDraft(true); pendingDeepQA.value = draft; question.value = draft.problem;
});
watch(()=>privateScopeIds.value.join(','),(value,old)=>{if(props.privateMode&&value!==old&&!route.query.session_id)startDraft();});
onActivated(() => {
  if(!props.privateMode && route.path==='/chat' && route.query.knowledge_node_id && !route.query.session_id && pageInitialized.value)startDraft();
  else void syncRouteSession();
});
onBeforeUnmount(() => {
  controller?.abort();
  stopStreamTimer();
  window.removeEventListener("resize", updateSidebarMode);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("pointerdown", onSelectionPointerDown);
  window.removeEventListener("scroll", dismissSelectionAction, true);
  window.removeEventListener("keydown", onContextMenuEscape);
});
</script>

<template>
  <section class="chat-workspace" aria-label="可信问答">
    <Teleport to="#chat-sidebar-slot" :disabled="compactSidebar||privateMode">
    <aside class="conversation-sidebar" aria-label="会话历史">
      <div class="sidebar-head">
        <h2>对话</h2>
        <button class="icon-button" type="button" title="新建对话" :disabled="sending || loading" @click="startDraft()">＋</button>
      </div>
      <RouterLink v-if="privateMode" to="/materials">返回我的资料</RouterLink>
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
          </button>
          <button
            type="button"
            class="conversation-delete"
            :aria-label="'删除会话：' + item.title"
            :title="'删除会话：' + item.title"
            :disabled="sending"
            @click.stop="deleteSession(item)"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <path d="M7 3.5h6m-9 2h12m-10.5 0 .7 10.1c.1.8.7 1.4 1.5 1.4h4.6c.8 0 1.4-.6 1.5-1.4l.7-10.1M8 8v6m4-6v6" />
            </svg>
          </button>
          <button v-if="compactSidebar" type="button" class="conversation-more" :aria-label="'会话操作：' + item.title" @click="openCompactMenu($event, item)">⋯</button>
        </div>
        <p v-if="!loading && sessions.length === 0" class="history-empty">还没有历史会话</p>
      </div>
    </aside>
    </Teleport>

    <main class="chat-main">
      <div v-for="mode in (['user', 'builtin'] as const)" :key="mode" v-show="materialErrors[mode]" role="status" :data-testid="`materials-error-${mode}`">
        {{ materialErrors[mode] }} <button type="button" :disabled="materialsLoading[mode]" @click="refreshMaterial(mode)">重试资料</button>
      </div>
      <div v-if="sessionsError" role="alert" data-testid="sessions-load-error">{{ sessionsError }} <button type="button" :disabled="loading" @click="initializeConversations">重试会话列表</button></div>
      <div v-if="messagesError" role="alert" data-testid="messages-load-error">{{ messagesError }} <button type="button" @click="openSession({session_id: sessionId!, mode: selectedMode} as ChatSession)">重试会话消息</button></div>
      <header class="chat-header">
        <div>
          <p class="chat-source" data-testid="chat-source">奶蛙 · 学习问答</p>
          <h2>和奶蛙一起，把问题想明白。</h2>
          <p class="chat-header-hint">提问、追问，或一起梳理学习思路。</p>
        </div>
        <span v-if="selectedMode === 'builtin' && learningContext.question_id">当前学习题目 <button :disabled="sending" @click="router.replace({ path: '/chat', query: sessionId ? { session_id: sessionId, clear_context: '1' } : {} })">退出题目上下文</button></span>
      </header>


      <p v-if="error" class="chat-notice chat-notice--error" role="alert">{{ error }} <RouterLink v-if="error.includes('尚未配置问答模型')" to="/settings">查看设置</RouterLink></p>
      <p v-if="uncertainTurn && uncertainTurn.sessionId === sessionId" class="chat-notice" data-testid="chat-turn-recovery">已保留提问：{{ uncertainTurn.question }} <button :disabled="sending || retryChecking" @click="recoverUncertainTurn">{{ uncertainCanRetry ? '重试这条请求' : '读取这条请求状态' }}</button></p>
      <p v-if="feedbackNotice" class="chat-notice chat-notice--success">{{ feedbackNotice }}</p>
      <p v-if="privateMode&&!privateScopeIds.length" class="chat-notice chat-notice--setup">
        请先到<RouterLink to="/materials">资料库选择资料</RouterLink>，再开始限定问答。历史会话仍可阅读；没有明确资料范围时不能发送新问题。
      </p>

      <section ref="scrollBox" class="messages" aria-live="polite" :aria-busy="sending" @mouseup="onAnswerTextSelection" @keyup="onAnswerTextSelection">
        <div v-if="loading || sessionLoading" class="empty-state">{{ loading ? "正在读取会话和资料状态…" : "正在读取对话…" }}</div>
        <div v-else-if="messagesError" class="empty-state">消息尚未恢复，请使用上方重试按钮。</div>
        <div v-else-if="messages.length === 0" class="empty-state">
          <StudyMascot pose="chin" class="chat-companion"/>
          <strong>从一个问题开始</strong>
          <span>问一道题、一个知识点，或让奶蛙一起梳理学习思路。</span>
        </div>

        <article v-for="message in messages" :key="message.message_id" class="message-row" :class="`message-row--${message.role}`">
          <div class="message-body">
            <div v-if="message.role === 'assistant'" class="assistant-message-heading"><StudyMascot pose="pencil" /><strong>奶蛙</strong></div>
            <div v-if="message.role === 'assistant' && message.status === 'generating'" class="response-progress" role="status" data-testid="response-progress">
              <span v-if="message.message_id === activeStreamMessageId" class="response-progress__dots" aria-hidden="true"><i></i><i></i><i></i></span>
              <span>{{ message.message_id === activeStreamMessageId ? streamStageLabel : "这次回答尚未完成。" }}</span>
              <span v-if="message.message_id === activeStreamMessageId" class="response-progress__time" aria-hidden="true">{{ streamElapsedSeconds }} 秒</span>
            </div>
            <div v-if="message.status !== 'generating' || Boolean(message.content)" class="message-bubble" :class="{ 'message-bubble--collapsed': messageIsLong(message) && !isExpanded(message.message_id), 'message-bubble--selectable': message.role === 'assistant' && message.status === 'completed' }">
              <MarkdownContent v-if="message.role === 'assistant' && message.content" :text="chatAnswerText(message.content)" />
              <MarkdownContent v-else-if="message.content && message.content.includes('\n> ')" :text="message.content" />
              <p v-else>{{ message.content || (message.status === 'cancelled' ? '已停止生成。' : '回答生成失败。') }}</p>
            </div>
            <button v-if="messageIsLong(message)" type="button" class="text-action" @click="toggleExpanded(message.message_id)">
              {{ isExpanded(message.message_id) ? "收起回答" : "展开完整回答" }}
            </button>
            <PracticeRequestCard v-if="message.practice_request_id&&!privateMode" :request-id="message.practice_request_id" />
            <PersonalQuestionResult v-if="message.personal_generation?.question_ids.length && !privateMode" :generation="message.personal_generation" />
            <GenerationFailureNotice v-if="message.personal_generation && !privateMode" :generation="message.personal_generation" />
            <section v-if="message.personal_training && !privateMode" class="personal-training-chat-result" data-testid="personal-training-chat-result" aria-label="专项训练操作结果">
              <p>{{ message.personal_training.summary }}</p>
              <RouterLink v-if="message.personal_training.training_id && (message.personal_training.item_count ?? 0) > 0 && ['active', 'paused', 'completed'].includes(message.personal_training.status ?? '')" :to="{ path: '/study', query: { mode: 'personal', owner_session_id: message.personal_training.owner_session_id, training_id: message.personal_training.training_id } }">进入专项练习</RouterLink>
              <ul v-else-if="message.personal_training.trainings?.length">
                <li v-for="training in message.personal_training.trainings.filter(item => ['active', 'paused', 'completed'].includes(item.status))" :key="training.training_id">
                  <RouterLink :to="{ path: '/study', query: { mode: 'personal', owner_session_id: message.personal_training.owner_session_id, training_id: training.training_id } }">进入专项练习 · {{ training.summary }}</RouterLink>
                </li>
              </ul>
            </section>
            <PersonalGenerationConfirmation v-if="!privateMode && message.personal_generation_confirmation && message.message_id === messages.filter(item => item.role === 'assistant').at(-1)?.message_id" :confirmation="message.personal_generation_confirmation" :busy="sending" @selection-change="onGenerationNodeSelection(message, $event)" @confirm="confirmGeneration(message, $event)" @confirm-targets="confirmGenerationTargets(message, $event)" @cancel="cancelGeneration(message)" />
            <button v-if="message.role === 'assistant' && message.status === 'failed' && message.retryable !== false" :disabled="sending || retryChecking" @click="retryLearningMessage(message)">重试这条回复</button>
            <button v-else-if="message.role === 'assistant' && message.status === 'failed'" :disabled="sending" @click="editFailedMessage(message)">编辑原提问</button>
            <div v-if="message.role === 'assistant' && message.status === 'completed'" class="message-actions">
              <span class="response-duration" :title="message.response_duration_ms == null ? '旧回答没有保存耗时' : '包含资料检索与回答生成的总耗时'">{{ formatResponseDuration(message.response_duration_ms) }}</span>
              <button type="button" class="text-action" @click="copyAnswer(chatAnswerText(message.content))">复制</button>
            </div>
          </div>
        </article>
      </section>

      <form class="composer" @submit.prevent="send()">
        <div v-if="quotedAnswers.length" class="composer-quotes" aria-label="已引用的回答内容" data-testid="composer-quotes">
          <blockquote v-for="item in quotedAnswers" :key="item.id" class="composer-quote">
            <span class="composer-quote__label">引用回答</span>
            <p>{{ item.text }}</p>
            <button type="button" :aria-label="'移除引用：' + item.text.slice(0, 24)" @click="removeQuotedAnswer(item.id)">移除</button>
          </blockquote>
        </div>
        <label class="sr-only" for="chat-question">你的问题</label>
        <div v-if="selectedMode === 'builtin' && learningContext.question_id" class="message-actions" aria-label="当前题目辅导">
          <button :disabled="sending" @click="askLearningAction('hint_1')">一点提示</button>
          <button :disabled="sending" @click="askLearningAction('hint_2')">下一步</button>
          <button :disabled="sending" @click="askLearningAction('solution')">讲解答案</button>
          <button :disabled="sending" @click="askLearningAction('process_review')">检查思路</button>
        </div>
        <textarea id="chat-question" v-model="question" :disabled="sending || loading" maxlength="4000" rows="1" placeholder="输入问题，或先选中回答内容作为引用…" @keydown.enter.exact="!$event.isComposing && ($event.preventDefault(), send())" />
        <div class="composer-footer"><small>{{privateMode?'围绕所选资料提问':'Enter 发送 · Shift + Enter 换行'}}</small><div><button type="button" :disabled="sending || loading || questionImageBusy" @click="pickQuestionImage">{{ questionImageBusy ? '识别中…' : '图片提问' }}</button><button v-if="sending" type="button" @click="cancel">停止生成</button><button class="send-button" type="submit" :disabled="!canSend">发送</button></div></div>
        <input ref="questionImageInput" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp" aria-label="选择题目图片" @change="onQuestionImage" />
        <p v-if="questionImageNotice" class="image-entry-notice" role="status">{{ questionImageNotice }}<button type="button" data-testid="image-variant-open" @click="openVariantPanel">生成变式练习</button></p>
        <p v-if="questionImageError" class="form-error" role="alert">{{ questionImageError }}</p>
        <section v-if="variantOpen" class="variant-panel" data-testid="image-variant-panel" aria-label="从图片题目生成变式练习">
          <header><strong>从图片题目生成个人变式练习</strong><button type="button" :disabled="variantBusy" @click="closeVariantPanel">关闭</button></header>
          <label>知识点<select v-model="variantKpId" data-testid="variant-kp" :disabled="variantKpsLoading||variantBusy"><option value="">{{variantKpsLoading?'加载中…':'请选择知识点'}}</option><option v-for="kp in variantKps" :key="kp.id" :value="kp.id">{{kp.name}}</option></select></label>
          <label>题量<select v-model.number="variantCount" data-testid="variant-count" :disabled="variantBusy"><option v-for="n in 5" :key="n" :value="n">{{n}} 道</option></select></label>
          <label>难度<select v-model="variantDifficulty" data-testid="variant-difficulty" :disabled="variantBusy"><option value="basic">基础</option><option value="improved">提高</option><option value="comprehensive">综合</option></select></label>
          <label>题型<select v-model="variantType" data-testid="variant-type" :disabled="variantBusy"><option value="single_choice">单选</option><option value="fill_blank">填空</option><option value="calculation">计算</option><option value="proof">证明</option><option value="subjective">主观</option></select></label>
          <label>生成方式<select v-model="variantMode" data-testid="variant-mode" :disabled="variantBusy"><option value="ai_enhanced">智能选题（优先复用题族）</option><option value="ai_generated">通用生成（模型出题）</option></select></label>
          <div class="variant-actions"><button type="button" class="primary" :disabled="variantBusy||!variantKpId" data-testid="variant-submit" @click="submitVariant">{{variantBusy?'生成中…':'生成变式练习'}}</button><button type="button" :disabled="variantBusy" @click="closeVariantPanel">取消</button></div>
          <p v-if="variantError" class="form-error" role="alert" data-testid="variant-error">{{variantError}}</p>
          <button v-if="variantNeedsFallback" type="button" data-testid="variant-fallback" :disabled="variantBusy" @click="fallbackVariant">改用通用生成（ai_generated）</button>
          <p v-if="variantResult?.question_ids.length" class="notice" data-testid="variant-result">已生成 {{variantResult.question_ids.length}} 道个人变式题并保存到个人题库；不会进入公共题库或今日卷。</p>
        </section>
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
.conversation-delete { display: grid; flex: 0 0 28px; width: 28px; min-height: 28px; margin-right: 3px; padding: 0; place-items: center; border: 0; border-radius: 8px; color: var(--text-tertiary); background: transparent; }
.conversation-delete svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.5; }
.conversation-delete:hover:not(:disabled) { color: var(--danger); background: #f7e8e6; }
.conversation-delete:focus-visible { color: var(--danger); outline: 2px solid color-mix(in srgb, var(--danger) 35%, transparent); outline-offset: 1px; }
.conversation-delete:disabled { cursor: not-allowed; opacity: .45; }
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
  .conversation-delete { flex-basis: 30px; width: 30px; min-height: 30px; color: var(--text-tertiary); }
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
.personal-training-chat-result { display: grid; gap: 8px; margin: 10px 0 4px; padding: 12px 14px; border: 1px solid #dbe6d8; border-radius: 10px; background: #f5f8f1; color: #425344; font-size: 13px; line-height: 1.55; }
.personal-training-chat-result p { margin: 0; white-space: pre-line; }
.personal-training-chat-result a { width: fit-content; color: #3c674c; font-weight: 600; text-decoration: underline; text-underline-offset: 2px; }
.personal-training-chat-result ul { display: grid; gap: 6px; margin: 0; padding-left: 18px; }
@media (max-width: 760px) {
  .conversation-row { flex: 0 0 176px; }
  .conversation-item { min-height: 48px; }
}
.scope-picker { margin: 13px 2px 17px; container-type: inline-size; }
.scope-picker__label { display: block; margin: 0 5px 7px; color: var(--text-tertiary); font-size: 11px; }
.scope-picker .scope-switch { display: flex; align-items: center; gap: 9px; min-height: 59px; padding: 9px 10px; border: 1px solid #d6e2ef; border-radius: 11px; background: rgba(255, 255, 255, .9); text-align: left; }
.scope-picker .scope-switch:hover:not(:disabled) { border-color: #a9c3df; background: #fff; }
.scope-picker .scope-switch:focus-visible { outline: 2px solid #8fb4dc; outline-offset: 2px; }
.scope-switch__icon { display: grid; flex: 0 0 30px; width: 30px; height: 30px; place-items: center; border-radius: 8px; color: #52769c; background: #edf4fc; }
.scope-switch__text { display: grid; flex: 1; min-width: 0; gap: 2px; margin: 0 !important; }
.scope-switch__text strong { color: var(--text); font-size: 12px; font-weight: 600; white-space: nowrap; }
.scope-switch__text small { margin: 0; color: var(--text-tertiary); font-size: 10px; white-space: nowrap; }
.scope-picker .scope-switch__change { display: flex; flex: 0 0 auto; align-items: center; gap: 3px; margin: 0; color: #647d99; font-size: 10px; }
.scope-switch__chevron { font-size: 14px; line-height: 1; }
@container (max-width: 190px) { .scope-picker .scope-switch__change { display: none; } }
@container (max-width: 145px) { .scope-picker .scope-switch__icon { display: none; } }
@media (max-width: 760px) {
  .scope-picker { width: min(300px, 100%); margin: 6px 0; }
  .scope-picker__label { display: none; }
  .scope-picker .scope-switch { min-height: 48px; padding: 6px 9px; }
}
</style>
