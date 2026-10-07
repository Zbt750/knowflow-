<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, onActivated, ref, watch } from "vue";
import MarkdownContent from "./MarkdownContent.vue";
import { useRouter } from "vue-router";
import { createChatSession, createDeepQA, fetchChatMessages, streamChatAnswer, type StudyContext, type AssistanceAction } from "../api/chat";
import {listPracticeRequests,planPracticeRequest,declinePracticeRequest,type PracticeRequest} from "../api/practiceRequests";
import { assistantConversationLink } from "../lib/studyContext";
import studyFrog from "../assets/study-frog-prone-v1.png";
import standingFrog from "../assets/study-frog-standing-v1.png";
import { confirmLearningTask } from "../api/learningTasks";
import { fetchLearningTask, cancelLearningTask, type LearningTask } from "../api/learningTasks";

const props = withDefaults(defineProps<{ sessionId: string | null; currentPlanId?: string | null; mascot?: boolean; studyContext?: StudyContext; currentWork?: string }>(), { currentPlanId: null, mascot: true });
const assistantSessionId = ref<string | null>(null);
const router=useRouter();const practiceRequests=ref<PracticeRequest[]>([]);
const requestListError=ref('');let deepRetry:{key:string;signature:string}|null=null;
function studyDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
const dayKey=()=>`learning-assistant:study:${studyDay()}`;
let assistantDay=studyDay();
async function refreshRequests(){try{practiceRequests.value=await listPracticeRequests();requestListError.value='';}catch{requestListError.value='练习需求暂时无法读取，请刷新；不会重新运行模型。';}}
onMounted(refreshRequests);onActivated(refreshRequests);
let requestPoll:ReturnType<typeof setInterval>|undefined;
onMounted(()=>{requestPoll=setInterval(refreshRequests,30000);});
onBeforeUnmount(()=>{if(requestPoll)clearInterval(requestPoll);});
async function ensureStudySession(){
  if(assistantDay!==studyDay()){assistantDay=studyDay();assistantSessionId.value=null;task.value=null;savedTaskId.value=null;messages.value=[];budget.value=90;stopPoll();}
  if(!assistantSessionId.value){const s=await createChatSession('今日学习','builtin',{purpose:'study'});assistantSessionId.value=s.session_id;try{localStorage.setItem(dayKey(),s.session_id);}catch{/* optional */}}
  return assistantSessionId.value;
}
async function deepQA(){
  if(busy.value)return;busy.value=true;error.value='';
  try{const id=await ensureStudySession();const context:StudyContext={...props.studyContext,surface:'study',conversation_id:id,
    task_id:task.value?.session_id===id?task.value.task_id:undefined};
    const problem=goal.value.trim()||'请详细解释当前学习内容。';const {generated_at:_generated,...signatureContext}=context as StudyContext&{generated_at?:string};
    const signature=JSON.stringify({id,context:signatureContext,problem,taskVersion:task.value?.draft_version??null});
    if(deepRetry?.signature!==signature)deepRetry={key:crypto.randomUUID(),signature};
    const response=await createDeepQA(id,context,problem,deepRetry.key);deepRetry=null;
    await router.push(assistantConversationLink(response.session_id,response.study_context));
  }catch(e){error.value=e instanceof Error?e.message:'暂时无法进入深入问答。';}finally{busy.value=false;}
}
async function handleRequest(request:PracticeRequest){
  if(busy.value)return;busy.value=true;error.value='';
  try{const id=await ensureStudySession();const result=await planPracticeRequest(request.id,id);task.value=result.task;remember(result.task.task_id);
    budget.value=result.task.budget_minutes;goal.value='';
    addMessage('assistant',result.request.status==='failed'?'当前正式练习库存不足或安排未完成；没有生成新题，也没有加入今日学习。':result.task.message);
    await refreshRequests();
  }catch(e){error.value=e instanceof Error?e.message:'读取建议未完成，请刷新状态。';await refreshRequests();
    const persisted=practiceRequests.value.find(r=>r.id===request.id);
    if(persisted?.planner_task_id){try{task.value=await fetchLearningTask(persisted.planner_task_id);remember(task.value.task_id);budget.value=task.value.budget_minutes;
      if(task.value.status==='running')startPoll(task.value.task_id,epoch);if(task.value.status==='ready')error.value='';}catch{/* explicit error remains */}}
  }finally{busy.value=false;}
}
async function declineRequest(request:PracticeRequest){try{await declinePracticeRequest(request.id);if(task.value?.task_id===request.planner_task_id)await refreshTask();await refreshRequests();}catch(e){error.value=e instanceof Error?e.message:'暂时无法撤回。';}}
let assistantController: AbortController | null = null;
let retryMessageId: string | null = null;
let retryGoal = "";
watch(() => `${props.studyContext?.question_id}:${props.studyContext?.attempt_id}`, () => { retryMessageId = null; retryGoal = ""; });
const emit = defineEmits<{ confirmed: [] }>();
const task = ref<LearningTask | null>(null);
const goal = ref("");
const budget = ref(90);
const busy = ref(false);
const error = ref("");
const refreshing = ref(false);
const savedTaskId = ref<string | null>(null);
const panel = ref<HTMLDetailsElement | null>(null);
const conversation = ref<HTMLElement | null>(null);
const messages = ref<Array<{ role: "user" | "assistant"; text: string }>>([]);
let lastReplyKey = "";
function addMessage(role: "user" | "assistant", text: string) {
  messages.value = [...messages.value, { role, text }].slice(-40);
}
function sendOnEnter(event: KeyboardEvent) {
  if (event.isComposing) return;
  event.preventDefault();
  void arrange();
}
watch(() => task.value, (updated) => {
  if (!updated?.metrics.commit) return;
  const key = `${updated.task_id}:${updated.draft_version}:${updated.status}:${updated.message}:${Boolean(updated.metrics.commit)}`;
  if (key === lastReplyKey) return;
  lastReplyKey = key;
  addMessage("assistant", updated.metrics.commit ? "题目已加入今日学习。你可以继续告诉我下一轮想怎么练。" : updated.message || statusLabels[updated.status] || "本次安排已更新。");
});
watch([messages, () => task.value?.status, busy], async () => {
  await nextTick();
  if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight;
}, { deep: true });
let epoch = 0;
let poll: ReturnType<typeof setTimeout> | undefined;
let pollGeneration = 0;
const labels: Record<string, string> = { search_knowledge: "定位知识范围", get_learning_state: "查看学习记录", find_questions: "查找可练题", get_question_availability: "查询题库库存", read_lesson: "读取知识讲解", validate_plan: "检查题目与时长" };
const statusLabels: Record<string, string> = { created: "等待安排", running: "正在安排", ready: "草案已校验", needs_info: "需要补充信息", answered: "查询完成", failed: "本次未完成", cancelled: "已取消" };
const storageKey = () => `learning-task:study:${studyDay()}`;
// Also refresh today's paper when a lost confirmation response is recovered by GET.
watch(() => task.value?.metrics.commit ? task.value.task_id : null, (committedId) => {
  if (committedId) emit("confirmed");
  if (committedId) void refreshRequests();
});
function stopPoll() { ++pollGeneration; if (poll) clearTimeout(poll); poll = undefined; }
function remember(id: string) { savedTaskId.value = id; try { localStorage.setItem(storageKey(), id); } catch { /* storage optional */ } }

watch(() => props.sessionId, async () => {
  const active = ++epoch;
  stopPoll(); busy.value = false; refreshing.value = false; savedTaskId.value = null; task.value = null; goal.value = ""; error.value = "";
  messages.value = []; lastReplyKey = "";
  assistantSessionId.value = null;
  try { assistantSessionId.value = localStorage.getItem(dayKey()); } catch { /* optional storage */ }
  if (assistantSessionId.value) {
    try {
      const history = await fetchChatMessages(assistantSessionId.value);
      if (active !== epoch) return;
      messages.value = history.map(m => ({ role: m.role, text: m.content })).slice(-40);
    } catch { if (active === epoch) assistantSessionId.value = null; }
  }
  let saved: string | null = null;
  try { saved = localStorage.getItem(storageKey()); } catch { /* storage optional */ }
  if (!saved) return;
  savedTaskId.value = saved;
  try {
    const restored = await fetchLearningTask(saved);
    if (active !== epoch) return;
    if (!messages.value.length) addMessage("user", restored.goal);
    task.value = restored; goal.value = ["failed", "cancelled"].includes(restored.status) ? restored.goal : ""; budget.value = restored.budget_minutes;
    if (restored.status === "running") startPoll(saved, active);
  } catch { if (active === epoch) error.value = "上次学习任务暂时无法读取，请刷新状态后检查。"; }
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

async function arrange(fresh = false, action: AssistanceAction = "auto") {
  if (busy.value || refreshing.value || !goal.value.trim() || !Number.isInteger(budget.value) || budget.value < 5 || budget.value > 240) return;
  if(action==='auto'&&/详细.*(?:讲|解释)|展开讲|去问答|深入问答/.test(goal.value)){await deepQA();return;}
  const active = ++epoch;
  busy.value = true; error.value = "";
  const submittedGoal = goal.value.trim();
  lastReplyKey = "";
  try {
    const id = await ensureStudySession();
    if (active !== epoch) return;
    const context: StudyContext = { ...props.studyContext, surface: "study", origin: "practice", conversation_id: id,
      daily_plan_id: props.currentPlanId ?? undefined, task_id: !fresh && task.value?.session_id === id ? task.value.task_id : undefined };
    addMessage("user", submittedGoal); addMessage("assistant", "");
    const replyIndex = messages.value.length - 1;
    assistantController = new AbortController();
    let replyId: string | null = null;
    let failed = false;
    let terminal = false;
    await streamChatAnswer(id, submittedGoal, (event, data) => {
      if (active !== epoch) return;
      if (event === "meta") {
        replyId = String(data.message_id);
        if (data.task_id) {
          const taskId = String(data.task_id); remember(taskId);
          task.value = { task_id: taskId, session_id: id, goal: submittedGoal, budget_minutes: budget.value,
            status: "running", trace: [], draft: null, message: "", error_code: null, metrics: {} };
        }
      }
      if (event === "delta") messages.value[replyIndex].text = data.replace ? String(data.text ?? "") : messages.value[replyIndex].text + String(data.text ?? "");
      if (event === "planner") { task.value = data as unknown as LearningTask; budget.value = task.value.budget_minutes; remember(task.value.task_id); }
      if (event === "done" || event === "error") terminal = true;
      if (event === "error") { failed = true; error.value = String(data.message ?? "回复未完成"); retryMessageId = replyId ?? (data.message_id ? String(data.message_id) : null); retryGoal = submittedGoal; }
    }, assistantController.signal, { assistant: true, study_context: context, qa_action: action,
      current_work: props.currentWork,
      retry_of_message_id: retryGoal === submittedGoal && action === "auto" ? retryMessageId ?? undefined : undefined });
    if (!terminal && active === epoch) throw new Error("回复连接已中断，请读取已保存的任务状态。");
    if (!failed && active === epoch) { goal.value = ""; retryMessageId = null; retryGoal = ""; }
    const history = await fetchChatMessages(id);
    if (active === epoch) messages.value = history.map(m => ({ role: m.role, text: m.content })).slice(-40);
  } catch (cause) {
    if (active === epoch) {
      error.value = cause instanceof Error ? cause.message : "安排未完成，可重试。";
      if (task.value) await refreshTask(active);
      if (active === epoch && ["ready", "needs_info", "answered"].includes(task.value?.status ?? "")) goal.value = "";
    }
  } finally {
    assistantController = null;
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
async function confirm() {
  if (!task.value?.draft_version || busy.value || refreshing.value) return;
  const active = epoch;
  busy.value = true; error.value = "";
  try {
    const result = await confirmLearningTask(task.value.task_id, task.value.draft_version);
    if (active === epoch) task.value = result;
  } catch (cause) {
    if (active === epoch) {
      const message = cause instanceof Error ? cause.message : "确认未完成";
      await refreshTask(active);
      if (active === epoch && !task.value?.metrics.commit) error.value = `${message}。请检查任务状态后再确认。`;
    }
  } finally { if (active === epoch) busy.value = false; }
}
onBeforeUnmount(() => { ++epoch; stopPoll(); });
function askHelp(action: AssistanceAction) {
  goal.value = ({ hint_1: "给我一点提示，不要告诉答案", hint_2: "请提示下一步，不要给最终结果", solution: "请讲解这道题的完整参考解答", process_review: "请辅助检查我的作答过程；缺少步骤时先问我" } as Record<string, string>)[action];
  void arrange(false, action);
}

function questionTypeLabel(value: string) {
  return ({ single_choice: "选择题", fill_blank: "填空题", calculation: "计算题", proof: "证明题", discussion: "讨论题", program: "程序题", subjective: "主观题" } as Record<string, string>)[value] ?? "练习题";
}
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
  <details ref="panel" class="learning-task" :class="{ 'learning-task--setup': !mascot }" data-testid="learning-task-panel">
    <summary class="frog-launcher" aria-label="奶蛙助手：安排学习" title="点击奶蛙，调整或补充练习" data-testid="study-frog-launcher">
      <span v-if="mascot" class="frog-portrait frog-portrait--prone" aria-hidden="true">
        <img :src="studyFrog" alt="" width="72" height="48" />
        <span class="frog-eyelid frog-eyelid--left"></span><span class="frog-eyelid frog-eyelid--right"></span>
      </span>
      <template v-else>
        <span class="frog-portrait frog-portrait--standing" aria-hidden="true">
          <img class="frog-standing" :src="standingFrog" alt="" width="120" height="132" />
          <span class="frog-eyelid frog-eyelid--left"></span><span class="frog-eyelid frog-eyelid--right"></span>
        </span>
        <span class="frog-welcome"><strong>今天想怎么练？</strong><span>点我说说要求，也可以直接在下面选范围。</span></span>
      </template>
      <span class="frog-status" v-if="busy || task?.status === 'running'">正在处理…</span>
      <span v-if="practiceRequests.some(r=>r.status==='pending')" data-testid="request-notification">{{practiceRequests.filter(r=>r.status==='pending').length}} 条练习需求</span>
    </summary>
    <div class="task-content" role="region" aria-label="奶蛙学习助手对话">
      <header class="frog-chat-header">
        <div><strong>奶蛙</strong><span>你的学习搭子</span><button type="button" :disabled="busy" @click="deepQA">深入问答 ↗</button></div>
        <button type="button" aria-label="收起奶蛙对话" @click="panel && (panel.open = false)">×</button>
      </header>
      <div ref="conversation" class="frog-conversation" data-testid="frog-conversation">
        <p v-if="requestListError" role="alert">{{requestListError}} <button @click="refreshRequests">刷新需求</button></p>
        <section v-if="practiceRequests.length" data-testid="pending-practice-requests">
          <p>{{practiceRequests.filter(r=>r.status==='pending').length}} 条新的练习需求</p>
          <div v-for="request in practiceRequests" :key="request.id">
            <p>{{request.user_request}}</p>
            <span v-if="request.status==='planning'">正在读取真实学习状态与题库…</span>
            <span v-else-if="request.status==='expired'">需求已过期，请重新提出。</span>
            <span v-else-if="request.status==='failed'">当前正式练习库存不足或安排未完成。</span>
            <button v-if="['pending','failed','proposed'].includes(request.status)" :disabled="busy" @click="handleRequest(request)">{{request.status==='proposed'?'查看已有方案':request.status==='failed'?'重新生成方案':'查看安排建议'}}</button>
            <button :disabled="busy" @click="declineRequest(request)">暂时不要</button>
          </div>
        </section>
        <div class="frog-message frog-message--assistant"><p>题目哪里不懂，或接下来想怎么练，都可以问我。安排练习会先给你方案，确认后再加入。</p></div>
        <div v-for="(message, index) in messages" :key="index" class="frog-message" :class="`frog-message--${message.role}`" :data-testid="`frog-message-${message.role}`">
          <MarkdownContent :text="message.text" />
        </div>
        <p v-if="busy || task?.status === 'running'" class="frog-thinking" role="status">奶蛙正在处理<span>…</span></p>
      <section v-if="task" aria-live="polite" data-testid="task-result">
        <p class="task-state">{{ task.metrics.commit ? '已加入今日学习' : statusLabels[task.status] }}</p>
        <details v-if="task.trace.length" class="task-progress"><summary>查看安排步骤</summary><ul class="task-steps"><li v-for="(step, index) in task.trace" :key="index">{{ labels[String(step.tool)] ?? '检查任务' }}{{ step.status === 'error' ? ' · 需调整' : ' · 完成' }}</li></ul></details>
        <div v-if="task.draft && task.status === 'ready'" class="task-draft">
          <p v-if="task.draft.review_minutes">建议复习：{{ (task.draft.review_nodes as Array<{name: string}>).map(n => n.name).join('、') }}</p>
          <ul class="task-draft-summary" data-testid="task-draft-summary"><li v-for="group in draftSummary(task.draft)" :key="group.key"><strong>{{ group.node }}</strong> · {{ group.type }} · {{ group.difficulty }} · {{ group.count }} 道 · 约 {{ group.minutes }} 分钟</li></ul>
          <p>{{ task.draft.rationale }}</p>
          <p v-for="warning in (task.draft.warnings as string[])" :key="warning" class="task-note">{{ warning }}</p>
          <template v-if="task.metrics.commit">
            <p class="task-note">题目已加入今日学习；知识复习可按此草案进行。</p>
          </template>
          <template v-else>
            <p class="task-note">尚未加入今日学习，确认后只添加题目，不改变掌握度。</p>
            <button v-if="(task.draft.questions as unknown[]).length" type="button" data-testid="task-confirm" :disabled="busy || refreshing || (goal.trim().length > 0 && goal.trim() !== task.goal) || budget !== task.budget_minutes" @click="confirm">{{ busy ? '正在确认…' : '确认加入今日学习' }}</button>
          </template>
        </div>
      </section>

      </div>
      <p v-if="error" role="alert" class="frog-chat-error">{{ error }}</p>
      <form class="frog-composer" @submit.prevent="arrange()">
        <div v-if="studyContext?.question_id" class="frog-chat-actions" aria-label="当前题目辅导">
          <button type="button" :disabled="busy" @click="askHelp('hint_1')">一点提示</button>
          <button type="button" :disabled="busy" @click="askHelp('hint_2')">下一步</button>
          <button type="button" :disabled="busy" @click="askHelp('solution')">讲解答案</button>
          <button type="button" :disabled="busy" @click="askHelp('process_review')">检查思路</button>
        </div>
        <label class="sr-only" for="frog-message-input">和奶蛙说说学习要求</label>
        <textarea id="frog-message-input" v-model="goal" rows="2" maxlength="1200" placeholder="问问当前题目，或说说想怎么练…" data-testid="task-goal" :disabled="busy || task?.status === 'running'" @keydown.enter.exact="sendOnEnter"></textarea>
        <div class="frog-composer-toolbar">
          <button type="submit" :disabled="busy || refreshing || task?.status === 'running' || goal.trim().length < 2 || !Number.isInteger(budget) || budget < 5 || budget > 240" data-testid="task-arrange">{{ busy ? '安排中…' : '发送' }}</button>
        </div>
        <div class="frog-chat-actions">
          <button v-if="task || savedTaskId" type="button" data-testid="task-refresh" :disabled="busy || refreshing" @click="refreshTask()">{{ refreshing ? '正在读取…' : '刷新状态' }}</button>
          <button v-if="task && task.status !== 'cancelled' && !task.metrics.commit" type="button" data-testid="task-cancel" @click="cancel">取消本次安排</button>
          <span>确认后才加入练习 · Shift + Enter 换行</span>
        </div>
      </form>
    </div>
  </details>
</template>

<style scoped>
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
.frog-chat-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.frog-chat-header > div { display: flex; align-items: baseline; gap: 9px; }
.frog-chat-header strong { font-size: 14px; font-weight: 550; color: var(--text); }
.frog-chat-header span { font-size: 11px; color: var(--text-tertiary); }
.frog-chat-header button { background: transparent; border: 0; font-size: 21px; color: var(--text-secondary); }
.frog-conversation { max-height: min(24vh, 180px); min-height: 64px; overflow-y: auto; overscroll-behavior: contain; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
.frog-message { max-width: 92%; padding: 10px 13px; border-radius: 13px; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.frog-message p { margin: 0; }
.frog-message--assistant { align-self: flex-start; background: #f6f7f8; color: var(--text); }
.frog-message--user { align-self: flex-end; background: #eaf3ff; color: #30445a; }
.frog-thinking { margin: 0; padding: 3px 8px; font-size: 12px; color: var(--text-tertiary); }
.task-draft { padding: 12px 14px; background: #fafbfc; border-radius: 12px; }
.task-state, .task-progress { font-size: 12px; color: var(--text-secondary); }
.task-progress summary { padding: 3px 0; }
.frog-composer { padding: 8px 14px; border-top: 1px solid var(--border); }
.frog-composer textarea { margin: 0; padding: 6px 0; min-height: 40px; max-height: 90px; resize: vertical; border: 0; background: transparent; box-shadow: none; font-size: 13px; }
.frog-composer-toolbar { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.frog-composer-toolbar label { font-size: 12px; color: var(--text-secondary); }
.frog-composer-toolbar input { width: 62px; border: 0; background: #f5f6f7; }
.frog-composer-toolbar button { border: 0; background: #edf3fa; color: #304b68; }
.frog-chat-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 8px; font-size: 10px; color: var(--text-tertiary); }
.frog-chat-actions button { padding: 0; background: transparent; border: 0; font-size: 11px; color: var(--text-secondary); }
.frog-chat-actions > span { margin-left: auto; }
.frog-chat-error { margin: 0; padding: 8px 16px; color: var(--danger); font-size: 12px; }

</style>
