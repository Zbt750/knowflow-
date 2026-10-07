<script setup lang="ts">
import { ref,watch } from "vue";
import { RouterLink } from "vue-router";
import {fetchPracticeRequest,sendPracticeRequest,declinePracticeRequest,type PracticeRequest} from "../api/practiceRequests";
const props=defineProps<{requestId:string}>();const request=ref<PracticeRequest|null>(null),busy=ref(false),error=ref("");
watch(()=>props.requestId,async id=>{try{request.value=await fetchPracticeRequest(id);}catch{error.value="暂时无法读取练习需求。";}},{immediate:true});
async function send(){if(!request.value?.source_conversation_id||busy.value)return;busy.value=true;error.value="";
  try{request.value=await sendPracticeRequest(request.value.id,request.value.source_conversation_id);}catch(e){error.value=e instanceof Error?e.message:"发送未完成，请检查状态。";
    try{request.value=await fetchPracticeRequest(props.requestId);if(request.value.status!=='draft')error.value='';}catch{/* keep original error */}}
  finally{busy.value=false;}}
async function decline(){if(!request.value||busy.value)return;busy.value=true;try{request.value=await declinePracticeRequest(request.value.id);}catch(e){error.value=e instanceof Error?e.message:"未能撤回。";}finally{busy.value=false;}}
</script>
<template><section class="practice-request-card" data-testid="practice-request-card" v-if="request">
  <template v-if="request.status==='draft'"><p>把这个练习需求交给奶蛙？发送后由它读取真实学习状态与题库，先给出方案，不会直接加题。</p>
    <button :disabled="busy||!request.details.target_knowledge_node_ids.length" @click="send" data-testid="request-send">发送给奶蛙</button>
    <button :disabled="busy" @click="decline">不用</button><small v-if="!request.details.target_knowledge_node_ids.length">请先说明具体知识点。</small></template>
  <template v-else-if="['pending','planning','proposed'].includes(request.status)"><p>✓ 已发送给奶蛙</p><RouterLink to="/study">去今日学习查看</RouterLink><small>尚未修改今日练习卷。</small></template>
  <p v-else-if="request.status==='accepted'">方案已加入今日学习。</p>
  <p v-else-if="request.status==='declined'">已撤回这份练习需求。</p>
  <p v-else-if="request.status==='expired'">这份练习需求已过期，请重新提出。</p>
  <p v-else>暂时未能安排，请在今日学习查看原因。</p>
  <p v-if="error" role="alert">{{error}}</p>
</section></template>
<style scoped>.practice-request-card{margin-top:10px;font-size:13px;color:var(--text-secondary)}p{margin:6px 0}button{margin-right:8px;border-radius:8px;padding:5px 10px}small{display:block;margin-top:6px}</style>
