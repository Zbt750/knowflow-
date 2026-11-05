<script setup lang="ts">
import StudyMascot from './StudyMascot.vue';
import { computed, ref, watch } from "vue";
import { appendPersonal, readBank, readGeneration, type GenerationResult, type PersonalQuestion } from "../api/personalQuestions";
import TodayAppendResult from './TodayAppendResult.vue';
import type {TodayAppendResult as AppendResult} from '../api/todayAppend';
import { fetchKnowledgeNode, fetchToday } from "../api/study";
import { isTodayActive } from "../types/practice";
import { typeLabel } from "../lib/labels";
import MarkdownContent from "./MarkdownContent.vue";
import GenerationDifficultySummary from './GenerationDifficultySummary.vue';
import GenerationOutcomeSummary from './GenerationOutcomeSummary.vue';

const props = defineProps<{ generation: GenerationResult }>();
const emit = defineEmits<{ added: []; ready: [] }>();
const questions = ref<PersonalQuestion[]>([]);
const loading = ref(false);
const adding = ref(false);
const error = ref("");
const nodeName = ref("");
const nodeCode = ref("");
const added = ref(false);
const appendResults=ref<AppendResult[]>([]);
const previewQuestions=computed(()=>{
  const joined=new Set(appendResults.value.filter(r=>r.plan_id===currentPlanId.value).flatMap(r=>r.items.map(i=>i.question_id)));
  return questions.value.filter(q=>!joined.has(q.id));
});
const postponed = ref(false);
const currentPlanId = ref<string | null>(null);
const hasReferenceOnly = computed(() => {
  const references = new Set(props.generation.reference_only_question_ids ?? []);
  return props.generation.question_ids.some(id => references.has(id));
});
const alreadyAdded = computed(() => {
  const ids = props.generation.question_ids ?? [];
  if (!ids.length || !currentPlanId.value || props.generation.plan_id !== currentPlanId.value) return false;
  const recorded = new Set(props.generation.appended_question_ids ?? []);
  return ids.every((id) => recorded.has(id)) || (props.generation.numbers?.length ?? 0) > 0;
});

async function loadQuestions(generation: GenerationResult): Promise<void> {
  appendResults.value=[];
  questions.value = [];
  nodeName.value = "";
  nodeCode.value = "";
  currentPlanId.value = null;
  error.value = "";
  added.value = alreadyAdded.value;
  postponed.value = false;
  if (!generation.question_ids?.length) return;

  loading.value = true;
  try {
    // Read persisted operation receipts, never infer a result from local flags.
    const stored=await readGeneration(generation.batch_id).catch(()=>null);
    if(stored && props.generation.batch_id===generation.batch_id)appendResults.value=stored.append_results??[];
    const wanted = new Set(generation.question_ids);
    const found = new Map<string, PersonalQuestion>();
    let offset = 0;
    let total = Number.POSITIVE_INFINITY;
    // Generation responses intentionally contain IDs, not a second question
    // payload. Reuse the existing personal-question read API for the preview.
    while (offset < total && found.size < wanted.size) {
      const page = await readBank("personal", undefined, "", offset, false, 100);
      total = page.total;
      for (const question of page.items) {
        if (wanted.has(question.id)) found.set(question.id, question);
      }
      if (!page.items.length) break;
      offset += page.items.length;
    }
    questions.value = generation.question_ids
      .map((id) => found.get(id))
      .filter((question): question is PersonalQuestion => Boolean(question));
    if (questions.value.length !== wanted.size) {
      error.value = "题目已保存，但完整预览暂时无法读取。可稍后从对应知识节点的题目列表查看。";
    }
    const nodeIds = [...new Set(questions.value.map((question) => question.kp_id))];
    if (nodeIds.length === 1) {
      try {
        const detail = await fetchKnowledgeNode(nodeIds[0]);
        nodeName.value = detail.node.name;
        nodeCode.value = detail.node.code;
      } catch {
        error.value ||= "题目已保存；所属知识节点名称暂时无法读取。";
      }
    }
    // Creating the first paper can remount the study panel. Its persisted chat
    // result predates the append response, so recover membership from today's
    // actual items instead of showing an already-added batch as still pending.
    try {
      const today = await fetchToday();
      if (isTodayActive(today)) {
        currentPlanId.value = today.plan_id;
        const currentIds = new Set(today.items.map(item => item.question_id));
        added.value = [...wanted].every(id => currentIds.has(id));
      }
    } catch {
      error.value ||= "题目已保存；加入今日学习的状态暂时无法核对，请稍后重试。";
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "题目预览暂时无法读取。";
  } finally {
    loading.value = false;
    emit("ready");
  }
}

async function addToToday(): Promise<void> {
  if (adding.value || !questions.value.length) return;
  adding.value = true;
  error.value = "";
  try {
    const today = await fetchToday();
    const planId = isTodayActive(today) ? today.plan_id : undefined;
    if (!planId && !window.confirm(
      `今天还没有学习卷。继续后会创建今日学习，并加入这 ${props.generation.question_ids.length} 道题。是否继续？`,
    )) return;

    const result = await appendPersonal(props.generation.question_ids, planId);
    if(result.append_result && !appendResults.value.some(item=>item.operation_id===result.append_result!.operation_id))appendResults.value.push(result.append_result);
    currentPlanId.value = result.plan_id;
    added.value = true;
    postponed.value = false;
    emit("added");
  } catch (cause) {
    const recovered=await readGeneration(props.generation.batch_id).catch(()=>null);
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const receipts=recovered?.append_results??[];
    const covered=new Set(receipts.filter(r=>r.study_date===today).flatMap(r=>r.items.map(i=>i.question_id)));
    appendResults.value=receipts;
    if(props.generation.question_ids.every(id=>covered.has(id))){currentPlanId.value=receipts.find(r=>r.study_date===today)!.plan_id;added.value=true;emit('added');}
    else error.value = '加入结果暂未确认，已先查询原操作状态；请刷新状态后再操作，不会自动重新追加。';
  } finally {
    adding.value = false;
  }
}

watch(() => props.generation.batch_id, () => { void loadQuestions(props.generation); }, { immediate: true });
</script>

<template>
  <section class="generated-question-result" data-testid="personal-generation-result" :data-generation-batch="generation.batch_id" aria-live="polite">
    <header class="generation-result-heading"><strong>{{ hasReferenceOnly ? '已保存的个人参考练习' : '通过检查并保存的练习题' }}</strong><StudyMascot pose="pencil"/></header>
    <p v-if="hasReferenceOnly" role="note">包含尚未完整独立核验答案的参考题；保存不代表答案正确性已获证明，不计入正式毕业证据。</p>
    <GenerationOutcomeSummary :generation="generation" />
    <p v-if="nodeName">所属知识点：{{ nodeName }}</p>
    <p v-else-if="questions.length">所属知识节点已绑定</p>
    <p v-if="loading" role="status">正在读取刚保存的题目…</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" :disabled="loading" @click="loadQuestions(generation)">重新读取题目</button></p>
    <TodayAppendResult v-for="result in appendResults" :key="result.operation_id" :result="result"/>
    <p v-if="(added || alreadyAdded) && !appendResults.length" role="status">这批题已在学习卷中；旧记录没有可恢复的本次入卷详情。</p>
    <p v-else-if="postponed" role="status">已暂不加入。题目仍保存在对应知识节点的题目列表中。</p>
    <div class="generated-question-result__actions">
      <button v-if="!added && !alreadyAdded && !postponed" type="button" :disabled="adding || loading || !questions.length" @click="addToToday">
        {{ adding ? "正在加入…" : "加入今日学习" }}
      </button>
      <button v-if="!added && !alreadyAdded && !postponed" type="button" :disabled="adding" @click="postponed = true">暂不加入</button>
      <RouterLink v-if="nodeCode" :to="{ path: '/knowledge', query: { node: nodeCode, tab: 'questions' } }">在知识树查看该节点题目</RouterLink>
      <RouterLink v-if="added || alreadyAdded" to="/study">查看今日学习</RouterLink>
    </div>
    <ol v-if="previewQuestions.length">
      <li v-for="question in previewQuestions" :key="question.id" class="generated-question-result__item">
        <small>AI练习题 · {{ typeLabel(question.question_type) }}</small>
        <GenerationDifficultySummary :summary="generation.difficulty_summaries?.[question.id] ?? question.difficulty_summary" />
        <MarkdownContent :text="question.stem" />
        <ul v-if="question.options" class="generated-question-result__options">
          <li v-for="(text, key) in question.options" :key="key"><strong>{{ key }}.</strong> <MarkdownContent :text="text" /></li>
        </ul>
      </li>
    </ol>
    <p class="hint">题目已保存到该知识节点；加入今日学习与保存题目是两个独立操作。个人练习不计入正式毕业证据。</p>
    <p v-if="generation.reference_only_question_ids?.length" class="hint" data-testid="general-generation-reference-notice">通用 AI 练习：已检查格式及可核验内容，参考答案尚未完整独立验证；可练习和记录，不用于正式毕业判断。</p>
  </section>
</template>

<style scoped>
.generated-question-result{flex:0 0 auto;margin:12px 0;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--surface)}
.generated-question-result__item{padding:10px 0;border-bottom:1px solid var(--border)}
.generated-question-result__item small{color:var(--text-secondary)}
.generated-question-result__options{padding-left:22px}
.generated-question-result__actions{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:10px}
@media(max-width:600px){.generated-question-result{padding:10px}.generated-question-result>ol{padding-left:16px}}
</style>
