<script setup lang="ts">
import { ref,watch,onBeforeUnmount,onMounted } from "vue";
import {onPracticeRequestsChanged,notifyPracticeRequestsChanged} from '../lib/practiceRequestChanges';
import { RouterLink } from "vue-router";
import {fetchPracticeRequest,sendPracticeRequest,declinePracticeRequest,type PracticeRequest} from "../api/practiceRequests";
import {fetchLearningTask,type LearningTask} from '../api/learningTasks';
import TodayAppendResult from './TodayAppendResult.vue';
import MarkdownContent from './MarkdownContent.vue';
import {createChatSession} from '../api/chat';
import {computed} from 'vue';
import {questionSourceLabel} from '../lib/questionSourceLabel';
import {typeLabel} from '../lib/labels';
const committedTask=ref<LearningTask|null>(null);
const props=defineProps<{requestId:string}>();const request=ref<PracticeRequest|null>(null),busy=ref(false),error=ref("");
type Preview={question_id:string;stem:string;options:Record<string,string>;kp_name:string;question_type:string;difficulty:string;source_category:string;minutes:number|null;question_version?:string};
const preview=computed(()=>((request.value?.details.preview_draft as {questions?:Preview[]}|undefined)?.questions??[]));
let readVersion=0;
async function refresh(){if(busy.value)return;const id=props.requestId,version=++readVersion;
  try{const current=await fetchPracticeRequest(id);if(version===readVersion&&props.requestId===id){request.value=current;error.value='';}}
  catch{if(version===readVersion)error.value="暂时无法读取练习需求，请刷新后确认状态。";}}
watch(()=>props.requestId,()=>{++readVersion;busy.value=false;request.value=null;committedTask.value=null;void refresh();},{immediate:true});
const unsubscribe=onPracticeRequestsChanged(refresh);
onMounted(()=>window.addEventListener('focus',refresh));
onBeforeUnmount(()=>{readVersion++;unsubscribe();window.removeEventListener('focus',refresh);});
watch(request,async value=>{
  const version=readVersion;
  committedTask.value=null;
  if(value?.status==='accepted'&&value.planner_task_id){
    const task=await fetchLearningTask(value.planner_task_id).catch(()=>null);
    if(version===readVersion&&request.value?.id===value.id&&request.value.status==='accepted'&&request.value.planner_task_id===value.planner_task_id)committedTask.value=task;
  }
});
async function send(){if(!request.value?.source_conversation_id||request.value.status!=='draft'||busy.value)return;
  const current=request.value,id=props.requestId,version=++readVersion;
  const owns=()=>version===readVersion&&props.requestId===id;
  busy.value=true;error.value="";
  try{const bound=current.details.target_study_session_id;
    const target=typeof bound==='string'?bound:(await createChatSession('奶蛙练习交接','builtin',{purpose:'study'})).session_id;
    if(!owns())return;
    const result=await sendPracticeRequest(current.id,current.source_conversation_id!,target);if(owns())request.value=result;
  }catch(e){if(!owns())return;error.value=e instanceof Error?e.message:"发送未完成，请检查状态。";
    try{const result=await fetchPracticeRequest(id);if(owns()){request.value=result;if(result.status!=='draft')error.value='';}}catch{/* keep original error */}}
  finally{if(owns())busy.value=false;}}
async function decline(){if(!request.value||request.value.status!=='draft'||busy.value)return;
  const id=props.requestId,version=++readVersion;const owns=()=>version===readVersion&&props.requestId===id;
  busy.value=true;error.value='';
  try{const result=await declinePracticeRequest(id);if(owns())request.value=result;}
  catch(e){if(!owns())return;error.value=e instanceof Error?e.message:"未能撤回。";
    try{const result=await fetchPracticeRequest(id);if(owns()){request.value=result;if(result.status==='declined')error.value='';}}catch{/* unknown is not success */}}
  finally{if(owns()){busy.value=false;notifyPracticeRequestsChanged();}}}
</script>
<template><section class="practice-request-card" data-testid="practice-request-card" v-if="request">
  <section v-if="request.status==='draft'&&preview.length" data-testid="request-question-preview">
    <article v-for="q in preview" :key="q.question_id" :data-question-id="q.question_id">
      <MarkdownContent :text="q.stem"/><div v-for="(text,key) in q.options" :key="key"><span>{{key}}.</span><MarkdownContent :text="text"/></div>
      <p>{{q.kp_name}} · {{typeLabel(q.question_type)}} · {{({basic:'基础',medium:'中等',hard:'较难'} as Record<string,string>)[q.difficulty]??q.difficulty}}</p>
      <p>来源：{{questionSourceLabel(q.source_category)}} · {{q.minutes==null?'暂无预计用时':`预计 ${q.minutes} 分钟`}} · 在线可练资格已校验</p>
    </article><p>尚未加入今日卷，等待确认。发送需求也不会直接入卷。</p>
  </section>
  <template v-if="request.status==='draft'"><p>把这个练习需求交给奶蛙？发送后由它读取真实学习状态与题库，先给出方案，不会直接加题。</p>
    <button :disabled="busy||!request.details.target_knowledge_node_ids.length" @click="send" data-testid="request-send">发送给奶蛙</button>
    <button :disabled="busy" @click="decline">不用</button><small v-if="!request.details.target_knowledge_node_ids.length">请先说明具体知识点。</small></template>
  <template v-else-if="['pending','planning','proposed'].includes(request.status)"><p>✓ 已发送给奶蛙</p><RouterLink to="/study">去今日学习查看</RouterLink><small>尚未修改今日练习卷。</small></template>
  <template v-else-if="request.status==='accepted'"><TodayAppendResult v-if="committedTask?.append_result" :result="committedTask.append_result"/><p v-else>方案已加入今日学习，正在读取入卷详情。</p></template>
  <p v-else-if="request.status==='declined'">已撤回这份练习需求。</p>
  <p v-else-if="request.status==='expired'">这份练习需求已过期，请重新提出。</p>
  <p v-else>暂时未能安排，请在今日学习查看原因。</p>
  <p v-if="error" role="alert">{{error}}</p>
</section></template>
<style scoped>.practice-request-card{margin-top:10px;font-size:13px;color:var(--text-secondary)}p{margin:6px 0}button{margin-right:8px;border-radius:8px;padding:5px 10px}small{display:block;margin-top:6px}</style>
