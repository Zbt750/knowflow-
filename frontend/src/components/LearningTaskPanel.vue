<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onActivated, reactive, ref, watch } from "vue";
import { assistantTerminal, type AssistantStatus } from '../lib/assistantTerminal';
import {notifyPracticeRequestsChanged,onPracticeRequestsChanged} from '../lib/practiceRequestChanges';
import { ownsTaskResult } from '../lib/taskResultOwner';
import MarkdownContent from "./MarkdownContent.vue";
import TodayAppendResult from './TodayAppendResult.vue';
import {questionSourceLabel} from '../lib/questionSourceLabel';
import { useRouter } from "vue-router";
import { ApiError } from "../api/client";
import { cancelGenerationConfirmation, createChatSession, listChatSessions, fetchChatMessages, streamChatAnswer, type ChatMessage, type StudyContext, type AssistanceAction, type PersonalGenerationMode } from "../api/chat";
import {listPracticeRequests,planPracticeRequest,declinePracticeRequest,type PracticeRequest} from "../api/practiceRequests";
import { saveDeepQADraft } from "../lib/deepQADraft";
import { restoreComposerDraft, takeComposerDraft } from "../lib/composerDraft";
import { assistantFailureMessage, assistantTurnFromHistory, createAssistantTurn, retryAssistantTurn, savedAssistantTurn, type AssistantTurn } from "../lib/assistantTurn";
import StudyMascot from './StudyMascot.vue';
import type { GenerationResult, GenerationConfirmation } from '../api/personalQuestions';
import PersonalQuestionResult from "./PersonalQuestionResult.vue";
import GenerationFailureNotice from './GenerationFailureNotice.vue';
import PersonalGenerationConfirmation from "./PersonalGenerationConfirmation.vue";
import { confirmLearningTask } from "../api/learningTasks";
import { fetchLearningTask, cancelLearningTask, type LearningTask } from "../api/learningTasks";
import { poseLibrary } from "../lib/mascotPoses";
import { resolveGenerationConfirmationReply } from "../lib/generationConfirmationReply";

type MascotPose = keyof typeof poseLibrary;
const props = withDefaults(defineProps<{ sessionId: string | null; currentPlanId?: string | null; mascot?: boolean; mascotPose?: MascotPose; studyContext?: StudyContext; currentWork?: string; reviewRequest?:boolean; open?:boolean }>(), { currentPlanId: null, mascot: true, mascotPose: 'read',open:false });
const assistantSessionId = ref<string | null>(null);
const router=useRouter();const practiceRequests=ref<PracticeRequest[]>([]);
const requestListError=ref('');
function studyDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
const dayKey=()=>`learning-assistant:study:${studyDay()}`;
let assistantDay=studyDay();
let requestReadVersion=0;
async function refreshRequests(){const version=++requestReadVersion,active=epoch;
  try{const rows=await listPracticeRequests();if(version!==requestReadVersion||active!==epoch)return;
    practiceRequests.value=rows;requestListError.value='';
    // Cancellation/confirmation in another card invalidates cached task state.
    // Only reread cards already owned by this study conversation.
    const owner=assistantSessionId.value;
    for(const id of new Set(messages.value.flatMap(m=>m.planner_task_id?[m.planner_task_id]:[]))){
      const snapshot=await fetchLearningTask(id).catch(()=>null);
      if(version!==requestReadVersion||active!==epoch||owner!==assistantSessionId.value)return;
      if(snapshot?.session_id===owner){
        // A GET started before a successful confirmation may arrive afterward.
        // A committed operation cannot transition back to an uncommitted preview.
        if(taskSnapshots[id]?.metrics.commit && !snapshot.metrics.commit)continue;
        taskSnapshots[id]=snapshot;if(!busy.value&&task.value?.task_id===id)task.value=snapshot;
      }
    }
  }catch{if(version===requestReadVersion&&active===epoch)requestListError.value='练习需求暂时无法读取，请刷新；不会重新运行模型。';}}
const unsubscribeRequests=onPracticeRequestsChanged(refreshRequests);
onMounted(refreshRequests);onActivated(refreshRequests);
let requestPoll:ReturnType<typeof setInterval>|undefined;
onMounted(()=>{requestPoll=setInterval(refreshRequests,30000);});
onMounted(()=>window.addEventListener('focus',refreshRequests));
onBeforeUnmount(()=>{++requestReadVersion;unsubscribeRequests();window.removeEventListener('focus',refreshRequests);if(requestPoll)clearInterval(requestPoll);});
async function ensureStudySession(){
  // The composer can be used before the async history/task restore settles.
  // Wait for the latest hydration so a refinement cannot create a fresh
  // session and lose the unconfirmed task bound to an existing conversation.
  await waitForSessionHydration();
  if(assistantDay!==studyDay()){assistantDay=studyDay();assistantSessionId.value=null;task.value=null;savedTaskId.value=null;messages.value=[];budget.value=90;generationConfirmation.value=null;generationConfirmationMessageId.value=null;generated.value=null;failedTurn.value=null;stopPoll();}
  if(!assistantSessionId.value){const s=await createChatSession('新对话','builtin',{purpose:'study'});assistantSessionId.value=s.session_id;try{localStorage.setItem(dayKey(),s.session_id);}catch{/* optional */}}
  return assistantSessionId.value;
}
async function deepQA(){
  if(busy.value)return;
  await waitForSessionHydration();
  const {submitted}=takeComposerDraft(goal.value);
  const problem=submitted;
  if(submitted)goal.value="";
  let succeeded=false;
  busy.value=true;error.value='';
  try{const id=assistantDay===studyDay()?assistantSessionId.value:null;
    const context:StudyContext={...props.studyContext,surface:'study',conversation_id:id??undefined,
      task_id:id&&task.value?.session_id===id?task.value.task_id:undefined};
    const draftId=saveDeepQADraft(id,context,problem);
    await router.push({path:'/chat',query:{study_draft:draftId}});
    succeeded=true;
  }catch(e){error.value=e instanceof Error?e.message:'暂时无法进入深入问答。';}
  finally{busy.value=false;if(!succeeded&&submitted)goal.value=restoreComposerDraft(goal.value,submitted);await nextTick(resizeComposer);}
}
async function handleRequest(request:PracticeRequest){
  if(busy.value)return;busy.value=true;error.value='';
  try{const bound=request.details.target_study_session_id;
    if(typeof bound==='string'){
      if(assistantSessionId.value!==bound){
        ++epoch;stopPoll();assistantController?.abort();assistantController=null;
        task.value=null;savedTaskId.value=null;messages.value=[];lastReplyKey='';failedTurn.value=null;
        generated.value=null;generationConfirmation.value=null;generationConfirmationMessageId.value=null;
        assistantSessionId.value=bound;
        restoreHistory(await fetchChatMessages(bound, 'study'));
      }
      try{localStorage.setItem(dayKey(),bound);}catch{/* optional */}
    }
    const id=await ensureStudySession();const result=await planPracticeRequest(request.id,id);task.value=result.task;remember(result.task.task_id);
    budget.value=result.task.budget_minutes;goal.value='';
    addMessage('assistant',result.request.status==='failed'?'当前正式练习库存不足或安排未完成；没有生成新题，也没有加入今日学习。':result.task.message,result.task.task_id);
    await refreshRequests();
  }catch(e){error.value=e instanceof Error?e.message:'读取建议未完成，请刷新状态。';await refreshRequests();
    const persisted=practiceRequests.value.find(r=>r.id===request.id);
    if(persisted?.planner_task_id){try{task.value=await fetchLearningTask(persisted.planner_task_id);remember(task.value.task_id);budget.value=task.value.budget_minutes;
      if(task.value.status==='running')startPoll(task.value.task_id,epoch);if(task.value.status==='ready')error.value='';}catch{/* explicit error remains */}}
  }finally{busy.value=false;}
}
async function declineRequest(request:PracticeRequest){try{await declinePracticeRequest(request.id);if(task.value?.task_id===request.planner_task_id)await refreshTask();await refreshRequests();}catch(e){error.value=e instanceof Error?e.message:'暂时无法撤回。';}}
let assistantController: AbortController | null = null;
const failedTurn = ref<AssistantTurn | null>(null);
const retryState = ref<"failed" | "unknown" | "generating">("failed");
const retryChecking = ref(false);
const failedTurnRetryable = ref(true);
const emit = defineEmits<{ confirmed: []; 'open-change':[opened:boolean] }>();
const task = ref<LearningTask | null>(null);
const goal = ref("");
const budget = ref(90);
const busy = ref(false);
const error = ref("");
const refreshing = ref(false);
const savedTaskId = ref<string | null>(null);
const panel = ref<HTMLDetailsElement | null>(null);
const expanded = ref(false);
// 展开的奶蛙对话框可用鼠标拖动（仅位置偏移，不改布局与业务状态）。
const chatDragOffset = ref({ x: 0, y: 0 });
let chatDragStart: { x: number; y: number; ox: number; oy: number } | null = null;
let chatDragBounds: { minX: number; maxX: number; minY: number; maxY: number } | null = null;
function onChatDrag(event: PointerEvent): void {
  if (!chatDragStart) return;
  const bounds = chatDragBounds ?? { minX: -400, maxX: 400, minY: -400, maxY: 400 };
  const x = chatDragStart.ox + event.clientX - chatDragStart.x;
  const y = chatDragStart.oy + event.clientY - chatDragStart.y;
  // 保证浮层始终留在视口内（至少留边距，可继续拖回）。
  chatDragOffset.value = {
    x: Math.min(bounds.maxX, Math.max(bounds.minX, x)),
    y: Math.min(bounds.maxY, Math.max(bounds.minY, y)),
  };
}
function stopChatDrag(): void {
  chatDragStart = null;
  window.removeEventListener("pointermove", onChatDrag);
}
function startChatDrag(event: PointerEvent): void {
  if ((event.target as HTMLElement).closest("button,a,input,textarea,select")) return;
  const el = panel.value?.querySelector(".task-content") as HTMLElement | null;
  const rect = el?.getBoundingClientRect();
  chatDragBounds = rect
    ? { minX: 8 - rect.left, maxX: window.innerWidth - rect.right - 8,
        minY: 8 - rect.top, maxY: window.innerHeight - rect.bottom - 8 }
    : null;
  chatDragStart = { x: event.clientX, y: event.clientY, ox: chatDragOffset.value.x, oy: chatDragOffset.value.y };
  window.addEventListener("pointermove", onChatDrag);
  window.addEventListener("pointerup", stopChatDrag, { once: true });
}
const chatDragStyle = computed(() => {
  if (!props.open) return undefined;
  const moved = { transform: `translate(${chatDragOffset.value.x}px, ${chatDragOffset.value.y}px)` };
  if (expanded.value) return moved;
  // 普通展开：保持原有尺寸，仅改为悬浮定位（不推挤题目），可拖动。
  return {
    ...moved,
    position: "fixed" as const,
    left: "auto",
    top: "auto",
    right: "16px",
    bottom: "16px",
    width: "min(420px, calc(100vw - 24px))",
    maxHeight: "72vh",
    zIndex: 60,
    margin: "0",
  };
});
const conversation = ref<HTMLElement | null>(null);
const composerInput = ref<HTMLTextAreaElement | null>(null);
const isComposing = ref(false);
const messages = ref<Array<{ message_id?: string; role: "user" | "assistant"; text: string; status?: AssistantStatus; planner_task_id?: string | null; personal_generation?: GenerationResult | null }>>([]);
const taskSnapshots = reactive<Record<string, LearningTask>>({});
const currentReplyTask = computed(() => messages.value.at(-1)?.planner_task_id === task.value?.task_id ? task.value : null);
const generated = ref<GenerationResult|null>(null);
const generationConfirmation = ref<GenerationConfirmation|null>(null);
const generationConfirmationMessageId = ref<string | null>(null);
const invalidGenerationCards = new Set<string>();
const generationMode = ref<PersonalGenerationMode>("ai_generated");
const launcherPose = computed<MascotPose>(() => {
  if (generated.value?.question_ids.length) return 'encourage';
  if (generationConfirmation.value) return 'pencil';
  if (busy.value || task.value?.status === 'running') return 'plan';
  if (currentReplyTask.value?.metrics.commit) return 'wave';
  return props.mascotPose;
});
const headerPose = computed<MascotPose>(() => generated.value?.question_ids.length ? 'teach' : launcherPose.value);
function closePanel() { expanded.value = false; chatDragOffset.value = { x: 0, y: 0 }; if (panel.value) panel.value.open = false; }
function handlePanelEscape() {
  if (expanded.value) expanded.value = false;
  else closePanel();
}
let lastReplyKey = "";
function addMessage(role: "user" | "assistant", text: string, plannerTaskId?: string) {
  messages.value = [...messages.value, { role, text, planner_task_id: plannerTaskId }].slice(-40);
}
function sendOnEnter(event: KeyboardEvent) {
  if (event.isComposing || isComposing.value) return;
  event.preventDefault();
  submitComposer();
}
function submitComposer() {
  if (isComposing.value) return;
  const draft = goal.value.trim();
  const confirmation = generationConfirmation.value;
  if (confirmation) {
    const reply = resolveGenerationConfirmationReply(draft, confirmation);
    if (reply.kind === "confirm") {
      goal.value = "";
      error.value = "";
      void confirmGeneration(reply.kpId);
      return;
    }
    if (reply.kind === "needs-node") {
      error.value = "请先在出题卡中选择知识点，或直接回复“确定 + 完整知识点名称”。";
      return;
    }
    if (reply.kind === 'unmatched-node') {
      error.value = `未找到知识点「${reply.requested}」。请从出题卡选择现有节点，或取消；没有生成题目。`;
      return;
    }
    // A pasted source, changed requirement or unrelated question is a NEW
    // turn. The pending card must not intercept every message in the composer.
  }
  void arrange();
}
function onGenerationNodeSelection(kpId: string | null) {
  if (!generationConfirmation.value) return;
  generationConfirmation.value = { ...generationConfirmation.value, selected_kp_id: kpId };
  error.value = "";
}
function resizeComposer() {
  const field=composerInput.value;
  if(!field)return;
  field.style.height="auto";
  const height=Math.min(field.scrollHeight,112);
  field.style.height=`${Math.max(42,height)}px`;
  field.style.overflowY=field.scrollHeight>112?"auto":"hidden";
}
watch(goal,()=>void nextTick(resizeComposer));
watch(() => task.value, updated => {
  if (updated) taskSnapshots[updated.task_id] = updated;
}, { flush: 'sync' });
async function revealGeneratedQuestion(batchId: string) {
  await nextTick();
  // An older preview can finish fetching after a newer reply. Only the latest
  // reply may reposition the conversation; background cards must not steal it.
  if (messages.value.at(-1)?.personal_generation?.batch_id !== batchId) return;
  const container = conversation.value;
  if (!container) return;
  const card = Array.from(container.querySelectorAll<HTMLElement>('[data-generation-batch]'))
    .find(element => element.dataset.generationBatch === batchId);
  if (card) container.scrollTop += card.getBoundingClientRect().top - container.getBoundingClientRect().top - 12;
}
function revealCurrentAppend():boolean {
  const joined = !busy.value ? currentReplyTask.value?.append_result : null;
  if (joined && conversation.value) {
    const container=conversation.value;
    const card=Array.from(container.querySelectorAll<HTMLElement>('[data-operation-id]')).find(node=>node.dataset.operationId===joined.operation_id);
    if(card){container.scrollTop+=card.getBoundingClientRect().top-container.getBoundingClientRect().top-12;return true;}
  }
  return false;
}
function onPanelToggle(event: Event) {
  if (event.target !== panel.value) return;
  emit('open-change',!!panel.value?.open);
  if (!panel.value?.open) { expanded.value = false; return; }
  const latestGeneration = messages.value.at(-1)?.personal_generation;
  if(revealCurrentAppend())return;
  if (latestGeneration?.question_ids.length) void revealGeneratedQuestion(latestGeneration.batch_id);
}
watch([messages, () => messages.value.at(-1)?.text, () => Object.values(taskSnapshots), () => task.value?.status, busy, generationConfirmation], async () => {
  await nextTick();
  const latestGeneration = messages.value.at(-1)?.personal_generation;
  if(revealCurrentAppend())return;
  if (!busy.value && latestGeneration?.question_ids.length) {
    await revealGeneratedQuestion(latestGeneration.batch_id);
    return;
  }
  if (conversation.value) conversation.value.scrollTo({ top: conversation.value.scrollHeight, behavior: 'instant' });
}, { deep: true });
let epoch = 0;
let poll: ReturnType<typeof setTimeout> | undefined;
let pollGeneration = 0;
const labels: Record<string, string> = { search_knowledge: "定位知识范围", get_learning_state: "查看学习记录", find_questions: "查找可练题", get_question_availability: "查询题库库存", read_lesson: "读取知识讲解", validate_plan: "检查题目与时长" };
const statusLabels: Record<string, string> = { created: "等待安排", running: "正在安排", ready: "草案已校验", needs_info: "需要补充信息", answered: "查询完成", failed: "本次未完成", cancelled: "已取消" };
const legacyStorageKey = () => `learning-task:study:${studyDay()}`;
const storageKey = (sessionId = assistantSessionId.value) => sessionId
  ? `learning-task:study:${studyDay()}:${sessionId}`
  : legacyStorageKey();
let sessionHydration:Promise<void>=Promise.resolve();
async function waitForSessionHydration(){
  let pending=sessionHydration;
  while(true){await pending;if(pending===sessionHydration)break;pending=sessionHydration;}
}
// Also refresh today's paper when a lost confirmation response is recovered by GET.
watch(() => task.value?.metrics.commit ? task.value.task_id : null, (committedId) => {
  if (committedId) emit("confirmed");
  if (committedId) void refreshRequests();
});
function stopPoll() { ++pollGeneration; if (poll) clearTimeout(poll); poll = undefined; }
function remember(id: string) {
  savedTaskId.value = id;
  const owner = task.value?.session_id ?? assistantSessionId.value;
  if (!owner) return;
  try { localStorage.setItem(storageKey(owner), id); } catch { /* storage optional */ }
}

watch(() => props.sessionId, async () => {
  const active = ++epoch;
  let finishHydration!:()=>void;
  const hydration=new Promise<void>(resolve=>{finishHydration=resolve;});
  sessionHydration=hydration;
  assistantController?.abort(); assistantController = null;
  stopPoll(); busy.value = false; refreshing.value = false; savedTaskId.value = null; task.value = null; goal.value = ""; error.value = "";
  messages.value = []; lastReplyKey = ""; failedTurn.value = null;
  for (const id of Object.keys(taskSnapshots)) delete taskSnapshots[id];
  generationConfirmation.value = null; generated.value = null;
  generationConfirmationMessageId.value = null;
  assistantSessionId.value = null;
  try { assistantSessionId.value = localStorage.getItem(dayKey()); } catch { /* optional storage */ }
  {
    try {
      const candidateId = assistantSessionId.value;
      // Local storage is only a pointer, not proof of session ownership. A
      // stale/older pointer to a QA chat must never become today's assistant.
      const ownSessions = await listChatSessions('builtin','study');
      if (active !== epoch) return;
      const todaySessions=ownSessions.filter(s=>s.mode==='builtin'&&s.purpose==='study'&&s.study_date===studyDay());
      const validCandidate=todaySessions.find(s=>s.session_id===candidateId)?.session_id??null;
      let recoverableTask:LearningTask|null=null;
      const readTaskHint=async(id:string|null):Promise<LearningTask|null>=>{
        if(!id)return null;
        try{
          const value=await fetchLearningTask(id);
          if(active!==epoch||!todaySessions.some(s=>s.session_id===value.session_id))return null;
          return value;
        }catch{return null;}
      };
      // A valid explicit topic pointer wins. If it is missing or stale, a
      // same-day, uncommitted task can recover the session that owns it.
      if(!validCandidate){
        let legacyId:string|null=null;
        try{legacyId=localStorage.getItem(legacyStorageKey());}catch{/* optional storage */}
        recoverableTask=await readTaskHint(legacyId);
        if(!recoverableTask){
          for(const session of todaySessions.slice(0,10)){
            let hint:string|null=null;
            try{hint=localStorage.getItem(storageKey(session.session_id));}catch{/* optional storage */}
            const value=await readTaskHint(hint);
            if(value&&!value.metrics?.commit&&['created','running','ready','needs_info','failed'].includes(value.status)){
              recoverableTask=value;break;
            }
          }
        }
      }
      assistantSessionId.value=validCandidate
        ??(recoverableTask&&!recoverableTask.metrics?.commit?recoverableTask.session_id:null)
        ??todaySessions[0]?.session_id??null;
      if(assistantSessionId.value)try{localStorage.setItem(dayKey(),assistantSessionId.value);}catch{/* optional */}
      const history = assistantSessionId.value ? await fetchChatMessages(assistantSessionId.value, 'study') : [];
      if (active !== epoch) return;
      restoreHistory(history);
      const historyTaskId=[...history].reverse().find(m=>m.role==='assistant'&&m.planner_task_id)?.planner_task_id??null;
      let savedHint:string|null=null;
      try{savedHint=localStorage.getItem(storageKey(assistantSessionId.value));}catch{/* optional storage */}
      let legacyHint:string|null=null;
      try{legacyHint=localStorage.getItem(legacyStorageKey());}catch{/* optional storage */}
      let legacyTask:LearningTask|null=null;
      if(legacyHint){
        legacyTask=legacyHint===recoverableTask?.task_id?recoverableTask:await readTaskHint(legacyHint);
        if(active!==epoch)return;
        if(!legacyTask||legacyTask.session_id!==assistantSessionId.value){
          try{localStorage.removeItem(legacyStorageKey());}catch{/* optional storage */}
          legacyHint=null;
        }
      }
      const selectedTaskId=historyTaskId??savedHint??(legacyTask?.session_id===assistantSessionId.value?legacyTask.task_id:null);
      savedTaskId.value=selectedTaskId;
      if(selectedTaskId){
        const restored=selectedTaskId===recoverableTask?.task_id?recoverableTask:await readTaskHint(selectedTaskId);
        if(active!==epoch)return;
        if(restored&&restored.session_id===assistantSessionId.value){
          task.value=restored;budget.value=restored.budget_minutes;
          if(!messages.value.length)addMessage('user',restored.goal);
          remember(restored.task_id);
          if(restored.status==='running')startPoll(restored.task_id,active);
        }else if(savedHint===selectedTaskId){
          try{localStorage.removeItem(storageKey(assistantSessionId.value));}catch{/* optional storage */}
          savedTaskId.value=null;
        }
      }
    } catch { if (active === epoch) assistantSessionId.value = null; }
    finally { finishHydration(); }
  }
  if(props.reviewRequest){goal.value='帮我安排这个知识点的复习';return;}
}, { immediate: true });

function startPoll(id: string, active: number) {
  stopPoll();
  const generation = pollGeneration;
  let failures = 0;
  const tick = async () => {
    try {
      const updated = await fetchLearningTask(id);
      if (active !== epoch || generation !== pollGeneration) return;
      failures = 0;
      task.value = updated;
      if (updated.status !== "running") { stopPoll(); return; }
    } catch {
      if (active !== epoch || generation !== pollGeneration) return;
      if (++failures >= 3) {
        stopPoll(); error.value = "暂时无法读取进度，请刷新任务状态；不会重新运行模型。"; return;
      }
    }
    if (active === epoch && generation === pollGeneration) poll = setTimeout(tick, 1500);
  };
  poll = setTimeout(tick, 1500);
}

// Only read the persisted task: never rerun the model or replace unsaved form edits.
async function refreshTask(active = epoch) {
  const id = task.value?.task_id ?? savedTaskId.value;
  if (!id || refreshing.value) return false;
  stopPoll(); refreshing.value = true;
  try {
    const updated = await fetchLearningTask(id);
    if (active !== epoch) return false;
    if (!task.value && !goal.value.trim()) { goal.value = updated.goal; budget.value = updated.budget_minutes; }
    task.value = updated; error.value = "";
    if (updated.status === "running") startPoll(id, active);
    return true;
  } catch {
    if (active === epoch) error.value = "任务状态暂时无法读取，请稍后刷新；已输入的目标和草案会保留。";
    return false;
  } finally { if (active === epoch) refreshing.value = false; }
}

async function confirmGeneration(kpId: string) {
  if (busy.value || !generationConfirmation.value || !generationConfirmationMessageId.value) return;
  if (assistantDay !== studyDay()) {
    goal.value = generationConfirmation.value.question;
    generationConfirmation.value = null; generationConfirmationMessageId.value = null;
    error.value = '已进入新的一天，昨天的确认卡不能用于今天；出题要求已放回输入框，请重新发送并确认。';
    return;
  }
  await arrange(false, "auto", kpId, undefined, generationConfirmation.value.question, generationConfirmationMessageId.value);
}
async function cancelGeneration() {
  if (busy.value || !assistantSessionId.value || !generationConfirmationMessageId.value) return;
  busy.value = true;
  try {
    await cancelGenerationConfirmation(assistantSessionId.value, generationConfirmationMessageId.value, 'study');
    generationConfirmation.value = null; generationConfirmationMessageId.value = null; error.value = '';
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '暂时无法取消，请稍后重试。'; }
  finally { busy.value = false; }
}
function restoreHistory(history: ChatMessage[]) {
  messages.value = history.map(m => ({ message_id: m.message_id, role: m.role, text: m.content || (m.status === 'failed' ? assistantFailureMessage(m.assistant_error_code) : ''), status: m.status, planner_task_id: m.planner_task_id, personal_generation: m.personal_generation })).slice(-40);
  const ownerSession = assistantSessionId.value;
  const ownerEpoch = epoch;
  for (const id of new Set(history.flatMap(m => m.planner_task_id ? [m.planner_task_id] : []))) {
    if (task.value?.task_id === id) taskSnapshots[id] = task.value;
    else void fetchLearningTask(id).then(snapshot => {
      if (epoch === ownerEpoch && assistantSessionId.value === ownerSession && snapshot.session_id === ownerSession) taskSnapshots[id] = snapshot;
    }).catch(() => { /* A missing history card never fails a different QA turn. */ });
  }
  const latest = [...history].reverse().find(m => m.role === 'assistant');
  generated.value = latest?.personal_generation ?? null;
  generationConfirmation.value = latest && !invalidGenerationCards.has(latest.message_id) ? latest.personal_generation_confirmation ?? null : null;
  generationConfirmationMessageId.value = latest?.personal_generation_confirmation ? latest.message_id : null;
  if (latest?.status !== 'failed') { failedTurn.value = null; error.value = ''; }
  if (latest?.status === 'failed' && assistantSessionId.value) {
    failedTurn.value = assistantTurnFromHistory(assistantSessionId.value, latest, history);
    retryState.value = 'failed';
    // Persisted content belongs to the Markdown message, never the error area.
    // Older failures may have no code; absence is not a second answer body.
    error.value = assistantFailureMessage(latest.assistant_error_code);
  }
  if (latest?.status === 'failed') failedTurnRetryable.value = latest.retryable !== false;
}
function editFailedReply() {
  if (!failedTurn.value) return;
  if (goal.value.trim()) { error.value = '输入框已有新的草稿，请先保留或发送该草稿，再编辑原提问。'; return; }
  goal.value = failedTurn.value.question;
  failedTurn.value = null;
  error.value = '原提问已放入输入框。修改后发送会开始一次新的请求。';
}
async function retryReply() {
  if (!failedTurn.value || !failedTurnRetryable.value || busy.value || retryChecking.value) return;
  const original = failedTurn.value;
  const previousState = retryState.value;
  let request: AssistantTurn | undefined;
  retryChecking.value = true;
  // A broken network connection is not proof that the server stopped. Read the
  // persisted turn first; only retry the same idempotent request afterwards.
  try {
    const history = await fetchChatMessages(original.sessionId, 'study');
    const saved = savedAssistantTurn(original, history);
    restoreHistory(history);
    if (saved?.status === 'completed' || saved?.status === 'cancelled') { failedTurn.value = null; error.value = ''; return; }
    if (saved?.status === 'generating') { retryState.value = 'generating'; error.value = '这条请求仍在处理，请稍后读取状态；不会重复发送。'; return; }
    if (saved?.retryable === false) { failedTurnRetryable.value = false; return; }
    request = retryAssistantTurn(original, saved);
    failedTurn.value = request;
    retryState.value = 'failed';
    if (previousState !== 'failed') { error.value = '已读取状态，本次回复尚未完成；可点击重试这条回复。'; return; }
  } catch { retryState.value = 'unknown'; error.value = '暂时无法确认这条请求的状态，请先读取状态；原提问已保留。'; }
  finally { retryChecking.value = false; }
  if (request) await arrange(false, 'auto', undefined, request);
}
async function arrange(fresh = false, action: AssistanceAction = "auto", confirmedKpId?: string, existingTurn?: AssistantTurn, confirmationQuestion?: string, confirmationMessageId?: string) {
  const submittedGoal = existingTurn?.question ?? confirmationQuestion ?? goal.value.trim();
  if (busy.value || refreshing.value || !submittedGoal || !Number.isInteger(budget.value) || budget.value < 5 || budget.value > 240) return;
  if(!existingTurn&&!confirmationMessageId&&action==='auto'&&/详细.*(?:讲|解释)|展开讲|去问答|深入问答/.test(submittedGoal)){await deepQA();return;}
  // Do not advance the request epoch while the watcher is still restoring the
  // active session. The hydration's stale-response guard uses that epoch.
  const hydrationEpoch=epoch;
  await waitForSessionHydration();
  if (hydrationEpoch!==epoch || busy.value || refreshing.value) return;
  const active = ++epoch;
  busy.value = true; error.value = "";
  if (!existingTurn && !confirmationMessageId) goal.value = '';
  if (!existingTurn && !confirmationMessageId) { generationConfirmation.value = null; generationConfirmationMessageId.value = null; }
  lastReplyKey = "";
  let request = existingTurn;
  const wire: {status: AssistantStatus} = {status: 'generating'};
  try {
    const id = request?.sessionId ?? await ensureStudySession();
    if (active !== epoch) return;
    const context: StudyContext = { ...props.studyContext, surface: "study", origin: "practice", conversation_id: id,
      daily_plan_id: props.currentPlanId ?? undefined, task_id: !fresh && task.value?.session_id === id ? task.value.task_id : undefined };
    request ??= createAssistantTurn(id, submittedGoal, { assistant: true, purpose: 'study', study_context: context, qa_action: action,
      current_work: props.currentWork, personal_generation_mode: generationMode.value,
      personal_generation_confirmed_kp_id: confirmedKpId,
      personal_generation_confirmation_message_id: confirmationMessageId }, messages.value);
    failedTurn.value = null;
    failedTurnRetryable.value = true;
    if (!existingTurn && !confirmationMessageId) addMessage("user", submittedGoal);
    const previousReplyIndex = existingTurn?.replyId ? messages.value.findIndex(message => message.message_id === existingTurn.replyId) : -1;
    if (previousReplyIndex >= 0) messages.value[previousReplyIndex] = { message_id: existingTurn?.replyId, role: 'assistant', text: '' };
    else addMessage("assistant", "");
    const replyIndex = previousReplyIndex >= 0 ? previousReplyIndex : messages.value.length - 1;
    assistantController = new AbortController();
    let replyId: string | null = null;
    let failed = false;
    let terminal = false;
    let confirmationRejected = false;
    await streamChatAnswer(id, submittedGoal, (event, data) => {
      if (active !== epoch) return;
      if (wire.status !== 'generating') return;
      wire.status = assistantTerminal(wire.status, event, data);
      messages.value[replyIndex].status = wire.status;
      if (event === "meta") {
        replyId = String(data.message_id);
        request!.replyId = replyId;
        messages.value[replyIndex].message_id = replyId;
        if (data.task_id) {
          const taskId = String(data.task_id); remember(taskId);
          task.value = { task_id: taskId, session_id: id, goal: submittedGoal, budget_minutes: budget.value,
            status: "running", trace: [], draft: null, message: "", error_code: null, metrics: {} };
        }
      }
      if (event === "delta") messages.value[replyIndex].text = data.replace ? String(data.text ?? "") : messages.value[replyIndex].text + String(data.text ?? "");
      if (event === "planner") { task.value = data as unknown as LearningTask; budget.value = task.value.budget_minutes; remember(task.value.task_id); }
      if (event === 'planner') messages.value[replyIndex].planner_task_id = task.value!.task_id;
      if (event === 'planner') { generated.value=null; generationConfirmation.value=null; }
      if (event === 'personal_generation') {
        generationConfirmation.value=null;
        generated.value=data as unknown as GenerationResult;
        messages.value[replyIndex].personal_generation = generated.value;
        if(generated.value.numbers?.length||generated.value.appended_question_ids?.length)emit('confirmed');
      }
      if (event === 'personal_generation_confirmation') {
        generationConfirmation.value=data as unknown as GenerationConfirmation;
        generationConfirmationMessageId.value=replyId;
        generated.value=null;
      }
      if (event === "done" || event === "error") terminal = true;
      if (event === 'done') notifyPracticeRequestsChanged();
      if (event === 'done' && wire.status === 'failed') {
        failed = true;
        error.value = assistantFailureMessage(String(data.code ?? ''));
      }
      if (event === "error") {
        failed = true;
        failedTurnRetryable.value = data.retryable !== false;
        if (data.message_id) request!.replyId = String(data.message_id);
        error.value = assistantFailureMessage(String(data.code ?? ''), String(data.message ?? '回复未完成'));
        if (data.code === 'study_session_expired' || (data.code === 'personal_generation_confirmation_invalid' && confirmationMessageId)) {
          confirmationRejected = true;
          if (confirmationMessageId) invalidGenerationCards.add(confirmationMessageId);
          if (data.code === 'study_session_expired') { assistantSessionId.value = null; assistantDay = studyDay(); }
          generationConfirmation.value = null; generationConfirmationMessageId.value = null;
          goal.value = restoreComposerDraft(goal.value, submittedGoal);
          failedTurn.value = null;
        }
      }
      if (event === 'done' && typeof data.answer === 'string') messages.value[replyIndex].text = data.answer;
    }, assistantController.signal, request.options);
    if (!terminal && active === epoch) throw new Error("回复连接已中断，请读取已保存的任务状态。");
    if (failed && !confirmationRejected && active === epoch) { failedTurn.value = request; retryState.value = 'failed'; }
    const history = await fetchChatMessages(id, 'study');
    if (active === epoch && assistantSessionId.value === id) {
      restoreHistory(history);
    }
  } catch (cause) {
    if (active === epoch) {
      // done reflects a persisted terminal reply. A failed history GET after
      // it is not a failed model turn and must never offer another send.
      if(wire.status==='completed'||wire.status==='cancelled'){
        failedTurn.value=null;error.value='';return;
      }
      error.value = cause instanceof ApiError
        ? assistantFailureMessage(cause.code, cause.message)
        : assistantFailureMessage(undefined, cause instanceof Error ? cause.message : "安排未完成，可重试。");
      if (cause instanceof ApiError && cause.code === 'personal_generation_confirmation_invalid' && confirmationMessageId) {
        invalidGenerationCards.add(confirmationMessageId);
        generationConfirmation.value = null; generationConfirmationMessageId.value = null;
        goal.value = restoreComposerDraft(goal.value, submittedGoal);
        failedTurn.value = null;
        const history = await fetchChatMessages(request?.sessionId ?? assistantSessionId.value!, 'study').catch(() => null);
        if (history && active === epoch && assistantSessionId.value === request?.sessionId) restoreHistory(history);
        return;
      }
      if (request) {
        failedTurn.value = request; retryState.value = 'unknown';
        try {
          const history = await fetchChatMessages(request.sessionId, 'study');
          if(active!==epoch||assistantSessionId.value!==request.sessionId)return;
          const saved = savedAssistantTurn(request, history);
          restoreHistory(history);
          if (saved?.status === 'completed') { failedTurn.value = null; error.value = ''; }
          else if (saved?.status === 'generating') { retryState.value = 'generating'; error.value = '连接已中断，这条请求仍在处理；请读取状态。'; }
          else if (saved?.status === 'failed') retryState.value = 'failed';
        } catch { /* Explicit recovery card keeps the original request and key. */ }
      } else goal.value = restoreComposerDraft(goal.value, submittedGoal);
      if (task.value) await refreshTask(active);
    }
  } finally {
    if(active===epoch)assistantController = null;
    if (active === epoch) busy.value = false;
  }
}

async function cancel() {
  assistantController?.abort();
  const id = task.value?.task_id ?? savedTaskId.value;
  if (!id) return;
  const active = epoch;
  try {
    const cancelled = await cancelLearningTask(id);
    if (active === epoch) { ++epoch; task.value = cancelled; busy.value = false; refreshing.value = false; stopPoll(); }
  } catch { if (active === epoch) error.value = "取消未确认，请刷新任务状态。"; }
}
function isCurrentTask(candidate: LearningTask) {
  const latestId = [...messages.value].reverse().find(m => m.planner_task_id)?.planner_task_id ?? task.value?.task_id;
  return latestId === candidate.task_id;
}
async function confirm(selectedTask?: LearningTask) {
  if (selectedTask) {
    if (!isCurrentTask(selectedTask)) return;
    const persisted=taskSnapshots[selectedTask.task_id];
    if(!persisted||persisted.session_id!==assistantSessionId.value||persisted.status!=='ready'||persisted.metrics.commit)return;
    task.value = persisted; budget.value = persisted.budget_minutes;
  }
  if (!task.value?.draft_version || task.value.status!=='ready' || task.value.metrics.commit || busy.value || refreshing.value) return;
  const active = epoch;
  busy.value = true; error.value = "";
  try {
    const result = await confirmLearningTask(task.value.task_id, task.value.draft_version);
    if (active === epoch && result.session_id === assistantSessionId.value) {
      task.value = result;
      taskSnapshots[result.task_id] = result;
    }
  } catch (cause) {
    if (active === epoch) {
      const message = cause instanceof Error ? cause.message : "确认未完成";
      await refreshTask(active);
      if (active === epoch && !task.value?.metrics.commit) error.value = `${message}。请检查任务状态后再确认。`;
    }
  } finally { if (active === epoch) busy.value = false; }
}
onBeforeUnmount(() => { ++epoch; assistantController?.abort(); assistantController = null; stopPoll(); });
function askHelp(action: AssistanceAction) {
  goal.value = ({ hint_1: "给我一点提示，不要告诉答案", hint_2: "请提示下一步，不要给最终结果", solution: "请讲解这道题的完整参考解答", process_review: "请辅助检查我的作答过程；缺少步骤时先问我" } as Record<string, string>)[action];
  void arrange(false, action);
}

function questionTypeLabel(value: string) {
  return ({ single_choice: "选择题", fill_blank: "填空题", calculation: "计算题", proof: "证明题", discussion: "讨论题", program: "程序题", subjective: "主观题" } as Record<string, string>)[value] ?? "练习题";
}
watch(()=>props.reviewRequest,async v=>{if(v){goal.value='帮我安排这个知识点的复习';await nextTick();if(panel.value)panel.value.open=true;}},{immediate:true});
function draftSummary(draft: Record<string, unknown> | null | undefined) {
  const questions = (draft?.questions as Array<{ question_id: string; kp_name?: string; question_type?: string; difficulty?: string; minutes?: number }> | undefined) ?? [];
  const groups = new Map<string, { key: string; node: string; type: string; difficulty: string; count: number; minutes: number }>();
  for (const question of questions) {
    const node = question.kp_name || "相关知识点";
    const type = questionTypeLabel(question.question_type || "");
    const difficulty = question.difficulty || "未标注难度";
    const key = `${node}|${type}|${difficulty}`;
    const group = groups.get(key) ?? { key, node, type, difficulty, count: 0, minutes: 0 };
    group.count += 1; group.minutes += question.minutes || 0; groups.set(key, group);
  }
  return [...groups.values()];
}
</script>

<template>
  <details ref="panel" :open="open" class="learning-task" :class="{ 'learning-task--setup': !mascot, 'learning-task--expanded': expanded }" data-testid="learning-task-panel" @toggle="onPanelToggle" @keydown.esc.stop="handlePanelEscape">
    <summary class="frog-launcher" aria-label="奶蛙助手：安排学习" title="点击奶蛙，调整或补充练习" data-testid="study-frog-launcher">
      <StudyMascot v-if="mascot" :pose="launcherPose" class="frog-planner-portrait frog-planner-portrait--compact"/>
      <span v-if="mascot" class="frog-launcher-label">问奶蛙</span>
      <template v-else>
        <StudyMascot pose="plan" class="frog-planner-portrait"/>
        <span class="frog-welcome"><strong>今天想怎么练？</strong><span>点我说说要求，也可以直接在下面选范围。</span></span>
        <span class="frog-launcher-action">让奶蛙安排学习 →</span>
      </template>
      <span class="frog-status" v-if="busy || task?.status === 'running'">正在处理…</span>
      <span v-if="practiceRequests.some(r=>r.status==='pending')" data-testid="request-notification">{{practiceRequests.filter(r=>r.status==='pending').length}} 条练习需求</span>
    </summary>
    <div class="task-content" role="region" aria-label="奶蛙学习助手对话" :style="chatDragStyle">
      <header class="frog-chat-header" style="cursor: move" title="按住拖动聊天框" @pointerdown="startChatDrag">
        <div class="frog-chat-brand"><StudyMascot :pose="headerPose" class="frog-chat-avatar"/><span><strong>奶蛙学习助手</strong><small>{{ generated?.question_ids.length ? '题目已保存，等你决定是否加入' : currentReplyTask?.metrics.commit ? currentReplyTask.draft?.kind === 'activity_schedule' ? '活动安排已确认，今日卷未改变' : '本次安排已加入今日学习' : '学习建议由你确认后执行' }}</small></span></div>
        <div class="frog-chat-header-actions">
          <button type="button" :disabled="busy" @click="deepQA">深入问答 ↗</button>
          <button type="button" class="frog-chat-expand" :aria-label="expanded ? '还原奶蛙对话' : '放大奶蛙对话'" :title="expanded ? '还原聊天框（Esc）' : '放大聊天框'" :aria-pressed="expanded" @click="expanded = !expanded">
            <svg v-if="!expanded" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8h5V3m13 5h-5V3M8 21v-5H3m13 5v-5h5"/></svg>
          </button>
          <button type="button" aria-label="收起奶蛙对话" @click="closePanel">×</button>
        </div>
      </header>
      <div ref="conversation" class="frog-conversation" data-testid="frog-conversation">
        <p v-if="requestListError" role="alert">{{requestListError}} <button @click="refreshRequests">刷新需求</button></p>
        <section v-if="practiceRequests.some(r=>r.status==='pending')" data-testid="pending-practice-requests">
          <p>{{practiceRequests.filter(r=>r.status==='pending').length}} 条新的练习需求</p>
          <div v-for="request in practiceRequests.filter(r=>r.status==='pending')" :key="request.id" :data-practice-request-id="request.id">
            <p>{{request.user_request}}</p>
            <span v-if="request.status==='planning'">正在读取真实学习状态与题库…</span>
            <span v-else-if="request.status==='expired'">需求已过期，请重新提出。</span>
            <span v-else-if="request.status==='failed'">当前正式练习库存不足或安排未完成。</span>
            <button v-if="['pending','failed','proposed'].includes(request.status)" :disabled="busy" @click="handleRequest(request)">{{request.status==='proposed'?'查看已有方案':request.status==='failed'?'重新生成方案':'查看安排建议'}}</button>
            <button :disabled="busy" @click="declineRequest(request)">暂时不要</button>
          </div>
        </section>
        <div v-if="!messages.length && !generated?.question_ids.length && !task && !practiceRequests.length" class="frog-chat-empty" data-testid="frog-chat-empty">
          <strong>今天想先处理什么？</strong>
          <p>可以问当前题、根据学习情况安排复习，或明确提出生成新题。新题会先展示给你，由你决定是否加入今日学习。</p>
        </div>
        <template v-for="(message, index) in messages" :key="message.message_id ?? index">
          <div class="frog-message" :class="`frog-message--${message.role}`" :data-message-id="message.message_id" :data-status="message.status" :data-testid="`frog-message-${message.role}`">
            <MarkdownContent :text="message.text" />
            <p v-if="message.status === 'failed'" class="task-note" data-testid="frog-message-failed-status">此条回复未完成，保留在原提问位置；不代表后续回复失败。</p>
          </div>
          <PersonalQuestionResult v-if="message.personal_generation?.question_ids.length" :generation="message.personal_generation" @ready="revealGeneratedQuestion(message.personal_generation.batch_id)" @added="emit('confirmed')" />
          <GenerationFailureNotice v-if="message.personal_generation" :generation="message.personal_generation" />
      <section v-for="ownedTask in ownsTaskResult(messages, index) && message.planner_task_id && taskSnapshots[message.planner_task_id] ? [taskSnapshots[message.planner_task_id]!] : []" :key="ownedTask.task_id" :data-owner-message-id="message.message_id" :data-task-id="ownedTask.task_id" aria-live="polite" data-testid="task-result">
       <template v-for="task in [ownedTask]" :key="task.task_id">
        <p v-if="!task.append_result" class="task-state">{{ task.metrics.commit ? task.draft?.kind === 'activity_schedule' ? '活动安排已确认，今日卷未改变' : '已加入今日学习' : statusLabels[task.status] }}</p>
        <p v-if="task.status === 'answered' && !task.draft" data-testid="no-valid-task-draft">本次只有建议或查询结果，没有有效的待确认草案；如需安排，请明确提出生成预览。</p>
        <p v-if="task.draft && task.status === 'ready' && !isCurrentTask(task)" data-testid="historical-task-draft">这是上一次的历史草案，仅供回看；请以当前请求的结果为准，不能在这里确认旧方案。</p>
        <TodayAppendResult v-if="task.append_result" :result="task.append_result"/>
        <details v-if="task.trace.length" class="task-progress"><summary>查看安排步骤</summary><ul class="task-steps"><li v-for="(step, index) in task.trace" :key="index">{{ labels[String(step.tool)] ?? '检查任务' }}{{ step.status === 'error' ? ' · 需调整' : ' · 完成' }}</li></ul></details>
        <div v-if="task.draft && task.status === 'ready'" class="task-draft">
          <section v-if="task.draft.kind === 'activity_schedule'" data-testid="activity-schedule">
            <p>复习活动预算：{{ task.draft.total_minutes }} 分钟；今日卷剩余预计作答耗时：{{ task.draft.paper_estimated_minutes ?? '未知' }} 分钟。两者口径不同。</p>
            <ol><li v-for="(activity,index) in (task.draft.activities as Array<{title:string;minutes:number;basis:string}>)" :key="index">{{ activity.minutes }} 分钟 · {{ activity.title }}<small>{{ activity.basis }}</small></li></ol>
          </section>
          <p v-if="task.draft.review_minutes">建议复习：{{ (task.draft.review_nodes as Array<{name: string}>).map(n => n.name).join('、') }}</p>
          <ul class="task-draft-summary" data-testid="task-draft-summary"><li v-for="group in draftSummary(task.draft)" :key="group.key"><strong>{{ group.node }}</strong> · {{ group.type }} · {{ group.difficulty }} · {{ group.count }} 道 · 约 {{ group.minutes }} 分钟</li></ul>
          <p>{{ task.draft.rationale }}</p>
          <p v-for="warning in (task.draft.warnings as string[])" :key="warning" class="task-note">{{ warning }}</p>
          <template v-if="task.metrics.commit">
            <p class="task-note">{{ task.draft.kind === 'activity_schedule' ? '活动安排已确认；今日卷未改变。' : task.append_result ? '已加入今日学习，题目详情和当前题号见入卷结果。' : '此历史操作已提交，但旧记录缺少可恢复的入卷明细；请到今日学习查看。' }}</p>
          </template>
          <template v-else>
            <div v-for="question in (task.draft.questions as Array<{question_id:string;stem?:string;options?:Record<string,string>;source_category?:string;question_version?:string;match_basis?:{shared_skill_tags?:string[];same_variant_group?:boolean};question_trust?:{practice_eligible?:boolean}}>)" :key="question.question_id" data-testid="pending-question-preview">
              <MarkdownContent v-if="question.stem" :text="question.stem"/>
              <div v-for="(text,key) in question.options" :key="key"><span>{{key}}.</span><MarkdownContent :text="text"/></div>
              <p v-if="question.match_basis" data-testid="bank-match-basis">匹配依据：同知识点、同题型<span v-if="question.match_basis.shared_skill_tags?.length">；共有技能标签：{{question.match_basis.shared_skill_tags.join('、')}}</span><span v-if="question.match_basis.same_variant_group">；同一变式组</span>。这只是可核实的匹配依据。</p>
              <small v-if="question.question_version">题目 {{question.question_id}} · 版本 {{question.question_version}}</small>
              <p>来源：{{questionSourceLabel(question.source_category??'unclassified_public')}} · {{question.question_trust?.practice_eligible?'在线可练资格已校验':'资格以服务端方案校验为准'}}；不等于毕业证据。</p>
            </div>
            <p class="task-note">{{ task.draft.kind === 'activity_schedule' ? '尚未确认活动安排；确认不会追加题目或改变掌握度。' : '尚未加入今日学习，确认后只添加题目，不改变掌握度。' }}</p>
            <button v-if="isCurrentTask(task) && (task.draft.kind === 'activity_schedule' || (task.draft.questions as unknown[]).length)" type="button" data-testid="task-confirm" :disabled="busy || refreshing || (goal.trim().length > 0 && goal.trim() !== task.goal)" @click="confirm(task)">{{ busy ? '正在确认…' : task.draft.kind === 'activity_schedule' ? '确认活动安排（不改今日卷）' : '确认加入今日学习' }}</button>
          </template>
        </div>
       </template>
      </section>
        </template>
        <p v-if="busy || task?.status === 'running'" class="frog-thinking" role="status">奶蛙正在处理<span>…</span></p>
        <PersonalGenerationConfirmation v-if="generationConfirmation" :confirmation="generationConfirmation" :busy="busy" @selection-change="onGenerationNodeSelection" @confirm="confirmGeneration" @cancel="cancelGeneration" />
      </div>
      <div v-if="error || failedTurn" role="alert" class="frog-chat-error" data-testid="frog-turn-error">
        <p v-if="error">{{ error }}</p>
        <template v-if="failedTurn"><p>已保留提问：{{ failedTurn.question }}</p><button v-if="failedTurnRetryable" type="button" :disabled="busy || retryChecking" @click="retryReply">{{ retryState === 'failed' ? '重试这条回复' : '读取这条请求状态' }}</button><button v-else type="button" :disabled="busy" @click="editFailedReply">编辑原提问</button></template>
      </div>
      <form class="frog-composer" @submit.prevent="submitComposer">
        <div v-if="studyContext?.question_id" class="frog-chat-actions" aria-label="当前题目辅导">
          <span class="frog-chat-actions-label">这道题</span>
          <button type="button" :disabled="busy" @click="askHelp('hint_1')">一点提示</button>
          <button type="button" :disabled="busy" @click="askHelp('hint_2')">下一步</button>
          <button type="button" :disabled="busy" @click="askHelp('solution')">讲解答案</button>
          <button type="button" :disabled="busy" @click="askHelp('process_review')">检查思路</button>
        </div>
        <label class="sr-only" for="frog-message-input">和奶蛙说说学习要求</label>
        <div class="frog-composer-entry">
          <textarea id="frog-message-input" ref="composerInput" v-model="goal" rows="1" maxlength="1200" placeholder="问问当前题目，或说说接下来想怎么练…" data-testid="task-goal" :disabled="busy || task?.status === 'running'" @compositionstart="isComposing = true" @compositionend="isComposing = false" @keydown.enter.exact="sendOnEnter" @input="resizeComposer"></textarea>
          <div class="frog-composer-toolbar">
            <button type="submit" :disabled="busy || refreshing || task?.status === 'running' || goal.trim().length < 2 || !Number.isInteger(budget) || budget < 5 || budget > 240" data-testid="task-arrange" :aria-label="busy ? '奶蛙安排中' : '发送给奶蛙'">{{ busy ? '安排中…' : '发送' }}</button>
          </div>
        </div>
        <div class="frog-composer-meta">
          <details class="frog-mode-settings">
            <summary>新题设置 <span>{{ generationMode === 'ai_generated' ? '奶蛙生成' : '快速练习' }}</span></summary>
            <fieldset class="frog-generation-mode" :disabled="busy || task?.status === 'running'">
              <legend>生成新题时使用</legend>
              <label><input v-model="generationMode" type="radio" value="ai_generated" name="frog-generation-mode" />奶蛙生成新题 <span>支持全部可考核知识点，生成题目、参考答案与解析，检查后保存</span></label>
              <label><input v-model="generationMode" type="radio" value="deterministic_fast" name="frog-generation-mode" />快速练习 <span>仅预设基础题型，本地生成，不调用模型</span></label>
              <small>仅在你明确要求出新题时生效；找题、问答和学习安排不受影响。</small>
            </fieldset>
          </details>
          <span class="frog-composer-shortcut">Enter 发送 · Shift + Enter 换行</span>
        </div>
        <div class="frog-chat-actions frog-chat-actions--utility">
          <button v-if="task || savedTaskId" type="button" data-testid="task-refresh" :disabled="busy || refreshing" @click="refreshTask()">{{ refreshing ? '正在读取…' : '刷新状态' }}</button>
          <button v-if="task && task.status !== 'cancelled' && !task.metrics.commit" type="button" data-testid="task-cancel" @click="cancel">取消本次安排</button>
          <span>安排由你确认 · 新题先预览，再决定是否加入</span>
        </div>
      </form>
    </div>
  </details>
</template>

<style scoped>
.frog-chat-header-actions{flex-wrap:wrap}
.learning-task { flex: 0 0 auto; margin: 0 0 12px; color: var(--text-secondary); font-size: 14px; }
.frog-launcher { display: flex; align-items: center; gap: 8px; list-style: none; padding: 0; border-radius: 10px; }
.frog-launcher::-webkit-details-marker { display: none; }
.frog-launcher img { display: block; width: 72px; height: 48px; object-fit: contain; }
.frog-portrait { position: relative; display: block; flex: 0 0 auto; transition: transform 140ms ease; }
.frog-launcher:hover .frog-portrait { transform: translateY(-2px); }
.frog-launcher:active .frog-portrait { transform: translateY(1px) scale(.94); }
.frog-eyelid { position: absolute; pointer-events: none; border-radius: 50%; background: #f7df72; transform: scaleY(0); animation: frog-blink 7s infinite; }
.frog-portrait--standing .frog-eyelid { width: 10%; height: 9%; top: 20%; }
.frog-portrait--standing .frog-eyelid--left { left: 46%; }
.frog-portrait--standing .frog-eyelid--right { left: 60%; }
.frog-portrait--prone .frog-eyelid { width: 10%; height: 16%; top: 27%; }
.frog-portrait--prone .frog-eyelid--left { left: 34%; }
.frog-portrait--prone .frog-eyelid--right { left: 60%; }
@keyframes frog-blink { 0%, 93%, 97%, 100% { transform: scaleY(0); } 94.5%, 95.5% { transform: scaleY(1); } }
@media (prefers-reduced-motion: reduce) {
  .frog-portrait { transition: none; }
  .frog-launcher:hover .frog-portrait, .frog-launcher:active .frog-portrait { transform: none; }
  .frog-eyelid { animation: none; }
}
.learning-task--setup { max-width: 760px; margin-bottom: 16px; }
.learning-task--setup .frog-launcher { gap: 18px; padding: 0; }
.frog-launcher img.frog-standing { width: 120px; height: 132px; }
.frog-welcome { display: grid; gap: 7px; max-width: 300px; line-height: 1.6; }
.frog-welcome strong { color: var(--text); font-size: 16px; font-weight: 500; }
.frog-welcome > span { font-size: 12px; }
@media (max-width: 600px) {
  .frog-launcher img.frog-standing { width: 88px; height: 100px; }
  .learning-task--setup .frog-launcher { gap: 10px; }
  .frog-welcome strong { font-size: 14px; }
}
.frog-launcher:focus-visible { outline: 2px solid #7a9fc1; outline-offset: 4px; }
.learning-task[open] .task-content { margin-top: 8px; padding: 12px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface, #fff); max-width: 620px; }
summary { cursor: pointer; padding: 9px 0; width: fit-content; }
summary span, .task-note, .task-draft li span { color: var(--text-tertiary); font-size: 12px; }
.task-content { max-height: 36vh; overflow-y: auto; padding: 4px 0 14px; }
textarea { width: 100%; min-height: 56px; border-radius: 10px; margin: 5px 0 9px; resize: vertical; }
.task-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
input { width: 76px; padding: 5px 8px; border-radius: 8px; }
button { padding: 6px 10px; border-radius: 8px; }
.task-steps { display: flex; flex-wrap: wrap; gap: 5px 16px; list-style: none; padding: 0; font-size: 12px; }
.task-draft ol { padding-left: 22px; }
.task-draft li { margin: 8px 0; }

/* A bounded conversation, leaving the practice sheet as the main surface. */
.learning-task[open] .task-content { width: min(680px, 100%); max-width: 100%; max-height: none; padding: 0; overflow: hidden; border-radius: 14px; box-shadow: 0 6px 20px rgb(36 49 63 / 6%); }
.frog-chat-header { display: flex; align-items: center; justify-content: space-between; padding: 13px 16px; border-bottom: 1px solid var(--border); }
.frog-chat-header > div { display: flex; align-items: center; gap: 9px; }
.frog-chat-header strong { font-size: 14px; font-weight: 550; color: var(--text); }
.frog-chat-header span { font-size: 11px; color: var(--text-tertiary); }
.frog-chat-header button { background: transparent; border: 0; font-size: 21px; color: var(--text-secondary); }
.frog-chat-header .frog-chat-expand { display: inline-flex; align-items: center; justify-content: center; min-width: 32px; min-height: 32px; padding: 5px; }
.frog-chat-expand svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.frog-conversation { max-height: min(24vh, 180px); min-height: 120px; overflow-y: auto; overscroll-behavior: contain; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; scroll-behavior: smooth; }
.frog-conversation > * { flex-shrink: 0; }
.frog-chat-empty { display: grid; align-content: center; justify-items: center; gap: 8px; min-height: 112px; max-width: 330px; margin: auto; padding: 12px; text-align: center; }
.frog-chat-empty strong { color: var(--text); font-size: 14px; font-weight: 550; }
.frog-chat-empty p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.75; }
.frog-message { max-width: 92%; padding: 10px 13px; border-radius: 13px; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.frog-message p { margin: 0; }
.frog-message--assistant { align-self: flex-start; background: #f6f7f8; color: var(--text); }
.frog-message--user { align-self: flex-end; background: #eaf3ff; color: #30445a; }
.frog-thinking { margin: 0; padding: 3px 8px; font-size: 12px; color: var(--text-tertiary); }
.task-draft { padding: 12px 14px; background: #fafbfc; border-radius: 12px; }
.task-state, .task-progress { font-size: 12px; color: var(--text-secondary); }
.task-progress summary { padding: 3px 0; }
.frog-composer { display: grid; gap: 8px; padding: 10px 14px 12px; border-top: 1px solid var(--border); background: #fffefb; }
.frog-composer-entry { display: flex; align-items: flex-end; gap: 8px; padding: 9px 10px 8px 13px; border: 1px solid #dfe5d8; border-radius: 12px; background: #fff; transition: border-color 140ms ease, box-shadow 140ms ease; }
.frog-composer-entry:focus-within { border-color: #92a588; box-shadow: none; }
.frog-composer textarea { flex: 1 1 auto; width: 0; margin: 0; padding: 5px 0; min-height: 42px; max-height: 112px; resize: none; border: 0; outline: 0; background: transparent; box-shadow: none; font-size: 13px; line-height: 1.65; }
.frog-composer-toolbar { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.frog-composer-toolbar label { font-size: 12px; color: var(--text-secondary); }
.frog-composer-toolbar input { width: 62px; border: 0; background: #f5f6f7; }
.frog-composer-toolbar button { flex: 0 0 auto; min-width: 58px; min-height: 34px; border: 0; border-radius: 9px; background: #e9efe3; color: #465d3e; font-size: 12px; }
.frog-composer-toolbar button:not(:disabled):hover { background: #dfe9d7; }
.frog-composer-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 22px; padding: 0 2px; }
.frog-mode-settings { position: relative; min-width: 0; }
.frog-mode-settings > summary { display: flex; align-items: center; gap: 6px; padding: 3px 0; color: var(--text-secondary); font-size: 11px; list-style: none; }
.frog-mode-settings > summary::-webkit-details-marker { display: none; }
.frog-mode-settings > summary::before { content: '+'; display: grid; place-items: center; width: 16px; height: 16px; border: 1px solid var(--border); border-radius: 50%; color: var(--text-tertiary); font-size: 12px; }
.frog-mode-settings[open] > summary::before { content: '−'; }
.frog-mode-settings > summary span { color: var(--text-tertiary); }
.frog-generation-mode { display: grid; gap: 8px; margin: 5px 0 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: #fff; }
.frog-generation-mode legend { padding: 0 4px; font-size: 10px; color: var(--text-tertiary); }
.frog-generation-mode label { display: grid; grid-template-columns: 15px minmax(0,1fr); align-items: start; gap: 3px 7px; font-size: 11px; color: var(--text-secondary); }
.frog-generation-mode label input { grid-row: span 2; width: auto; margin: 2px 0 0; }
.frog-generation-mode input { width: auto; margin: 0; }
.frog-generation-mode label span, .frog-generation-mode small { font-size: 10px; line-height: 1.5; color: var(--text-tertiary); }
.frog-generation-mode small { display: block; }
.frog-chat-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 8px; font-size: 10px; color: var(--text-tertiary); }
.frog-chat-actions button { padding: 0; background: transparent; border: 0; font-size: 11px; color: var(--text-secondary); }
.frog-chat-actions-label { margin-right: 2px; color: var(--text-tertiary); }
.frog-chat-actions > span { margin-left: auto; }
.frog-composer-shortcut { color: var(--text-tertiary); font-size: 10px; }
.frog-chat-actions--utility { justify-content: space-between; margin: 0; padding: 0 2px; }
.frog-chat-actions--utility > span { margin-left: auto; }
.frog-chat-error { margin: 0; padding: 8px 16px; color: var(--danger); font-size: 12px; }

</style>
