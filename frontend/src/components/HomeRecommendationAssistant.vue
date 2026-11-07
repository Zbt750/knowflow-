<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch,reactive,nextTick} from 'vue';
import {adjustHomePreview,adjustHomeDifficulty,confirmHomePreview,recoverHomePreview,readHomeSystemRecommendation,type HomeSystemRecommendation,type HomePreview,type HomePaper} from '../api/homeRecommendation';
import {createChatSession,fetchChatMessages,listChatSessions,streamChatAnswer,type ChatSession,type ChatMessage} from '../api/chat';
import {ApiError} from '../api/client';
import MarkdownContent from './MarkdownContent.vue';
import StudyMascot from './StudyMascot.vue';
import HomeFormulaContent from './HomeFormulaContent.vue';
import HomeRecommendationBaseline from './HomeRecommendationBaseline.vue';
import {homePaperCount,homeNodeCount} from '../lib/homePaperSummary';
import {homeStudyDay,homeDayKey,homeDayTitle} from '../lib/homeDailyConversation';
import {homeRecommendationFailure} from '../lib/homeRecommendationFailure';
import {homePreviewIdentity,coherentHomePreview,coherentHomePaper} from '../lib/homePreviewIdentity';
const props=defineProps<{selectedKpIds:string[];budget:string;previewTarget?:string;workbench?:boolean;readOnly?:boolean;formalPaper?:{plan_id:string;total_count:number;estimated_minutes:number}|null}>();
const emit=defineEmits<{confirmed:[];practice:[];scopeChange:[ids:string[]]}>();
const preview=ref<HomePreview|null>(null), input=ref(''), error=ref(''), busy=ref(false), session=ref('');
const difficultyBusy=ref(false),difficultyNotice=ref('');
const systemEditError=ref('');
const scopeSaving=ref(false),chatProcessing=ref(false),workloadDeciding=ref(false);
let scopeSaveSequence=0;
function resetOperationUi(){scopeSaveSequence++;scopeSaving.value=false;chatProcessing.value=false;workloadDeciding.value=false;}
const workloadCandidate=ref<HomePreview|null>(null);
const sessions=ref<ChatSession[]>([]), history=ref<Array<Pick<ChatMessage,'message_id'|'role'|'content'>>>([]);
const mode=ref<'adjust'|'qa'>('adjust');
const selectionDirty=ref(false), creatingTopic=ref(false), confirming=ref(false);
// Local invalidation is not proof that a server cancellation committed.
const previewUncertain=ref(false);
const storageKey='naiwa:home-recommendation:session:v1';
const homeUiRevision='home-no-evidence-restore-action-20261029-r1';
const systemSnapshot=ref<HomeSystemRecommendation|null>(null),systemLoading=ref(false),systemError=ref('');
const restoreNotice=ref('');
const dailyChat=ref<HTMLElement|null>(null),chatOpen=ref(false),chatLauncher=ref<HTMLButtonElement|null>(null);
async function openChat(){chatOpen.value=true;await nextTick();dailyChat.value?.focus?.();dailyChat.value?.scrollTo({top:dailyChat.value.scrollHeight});}
async function closeChat(){chatOpen.value=false;await nextTick();chatLauncher.value?.focus();}
const day=ref(homeStudyDay()),manualEditing=ref(false);
const scopeEditor=ref<HTMLElement|null>(null),scopeLauncher=ref<HTMLButtonElement|null>(null);
function onEscape(e:KeyboardEvent){if(e.key!=='Escape')return;if(manualEditing.value){e.preventDefault();void cancelScopeEdit();}else if(chatOpen.value){e.preventDefault();void closeChat();}}
let originalManualIds:string[]=[];
let originalVisibleScope:Array<{id:string;name:string}>=[];
const scopeDelta=ref<{retained:string[];removed:string[];added:string[]}|null>(null);
function toggleManualKp(id:string){emit('scopeChange',props.selectedKpIds.includes(id)?props.selectedKpIds.filter(k=>k!==id):[...props.selectedKpIds,id]);}
let dayTimer:ReturnType<typeof setInterval>|undefined;
const currentStorageKey=()=>props.workbench?homeDayKey(day.value):storageKey;
const rememberSession=(id:string)=>localStorage.setItem(currentStorageKey(),id);
function checkDay():boolean{
 if(!props.workbench||day.value===homeStudyDay())return true;
 resetOperationUi();
 generation++;controller?.abort();systemSnapshot.value=null;day.value=homeStudyDay();session.value='';preview.value=null;history.value=[];input.value='';error.value='';systemEditError.value='';topicFailure.value='';topicLoading.value=false;busy.value=false;creatingTopic.value=false;confirming.value=false;previewUncertain.value=false;selectionDirty.value=false;manualEditing.value=false;scopeDelta.value=null;
 void loadSystem();void restoreDaily();return false;
}
const checkDayOnFocus=()=>{checkDay();};
async function restoreDaily(){
 const token=generation;
 try{
  error.value='';systemEditError.value='';topicFailure.value='';
  const rows=await listChatSessions('builtin','study');if(!checkDay()||token!==generation)return;
  // Treat the scoped server response as the ownership allowlist. A stale local
  // daily pointer must never be sent to the home-preview resource API by itself.
  const studyRows=rows.filter(row=>row.mode==='builtin'&&row.purpose==='study');
  sessions.value=studyRows;
  const legacyPointer=localStorage.getItem(storageKey);
  // Older builds stored the homepage pointer in a shared key that could contain
  // a Q&A session id. Only migrate it when the server's study-scoped listing
  // positively identifies that id as a homepage conversation.
  const dailyPointer=localStorage.getItem(homeDayKey(day.value));
  const id=studyRows.find(row=>row.session_id===dailyPointer)?.session_id??studyRows.find(s=>s.title===homeDayTitle(day.value))?.session_id??
    (legacyPointer&&studyRows.some(row=>row.session_id===legacyPointer)?legacyPointer:null);
  if(id)await selectSession(id);
 }catch(e){if(token===generation){topicFailure.value=errorText(e);error.value=errorText(e);}}
}
async function beginScopeEdit(){
 chatOpen.value=false;
 if(props.readOnly||props.formalPaper||!checkDay())return;
 originalManualIds=[...(recommendedPaper.value?.selected_kp_ids??props.selectedKpIds)];originalVisibleScope=(recommendationView.value?.recommendations??[]).map(n=>({id:n.kp_id,name:n.name}));manualEditing.value=true;
 emit('scopeChange',[...(recommendedPaper.value?.selected_kp_ids??systemSnapshot.value?.recommendations.map(r=>r.kp_id)??props.selectedKpIds)]);
 await nextTick();
 scopeEditor.value?.focus?.();
}
async function cancelScopeEdit(){if(scopeSaving.value)return;emit('scopeChange',[...originalManualIds]);await nextTick();manualEditing.value=false;await nextTick();scopeLauncher.value?.focus?.();}
async function applyScopeEdit(){
 if(!props.selectedKpIds.length||busy.value||scopeSaving.value||!checkDay())return;
 const minutes=recommendedPaper.value?.budget_minutes??90;
 const saveId=++scopeSaveSequence;scopeSaving.value=true;
 try{
 await nextTick();const applied=await prepare('default',false,minutes);
 if(saveId!==scopeSaveSequence)return;
 if(pendingWorkload.value){manualEditing.value=false;await openChat();return;}
 if(applied&&preview.value?.draft&&usablePreview.value){
  manualEditing.value=false;
  const after=preview.value.draft.selected_kp_ids,before=originalVisibleScope.map(n=>n.id);
  const name=(id:string)=>preview.value?.draft?.scope_nodes?.find(n=>n.kp_id===id)?.name??originalVisibleScope.find(n=>n.id===id)?.name??id;
  scopeDelta.value={retained:after.filter(id=>before.includes(id)).map(name),removed:before.filter(id=>!after.includes(id)).map(name),added:after.filter(id=>!before.includes(id)).map(name)};
 }
 }finally{if(saveId===scopeSaveSequence)scopeSaving.value=false;}
}
let systemGeneration=0;
async function loadSystem(){const token=++systemGeneration;systemLoading.value=true;systemError.value='';try{const data=await readHomeSystemRecommendation();if(token===systemGeneration)systemSnapshot.value=data;}catch(e){if(token===systemGeneration)systemError.value=homeRecommendationFailure(e);}finally{if(token===systemGeneration)systemLoading.value=false;}}
const topicLoading=ref(false),topicFailure=ref(''),generatingPaper=ref(false);
const pending=reactive<Record<string,number>>({});
const chatPending=reactive<Record<string,number>>({});
const slots:Record<string,{task:HomePreview|null;revision:number}>={};
let requestSequence=0, slotSequence=0;
function clearForbiddenStudyBinding(id:string){
 if(!props.workbench||!id)return;
 if(localStorage.getItem(homeDayKey(day.value))===id)localStorage.removeItem(homeDayKey(day.value));
 sessions.value=sessions.value.filter(row=>row.session_id!==id);
 if(session.value===id){session.value='';preview.value=null;previewUncertain.value=false;history.value=[];selectionDirty.value=false;}
 topicFailure.value='';
 resetOperationUi();
 systemEditError.value='';
 error.value='首页学习会话当前不可访问。已停止使用该会话，没有自动重复提交；请重新询问奶蛙以开始新的今日学习会话。';
}
const isAccessForbidden=(e:unknown)=>e instanceof ApiError&&e.status===403&&e.code==='forbidden';
const topicPending=computed(()=>Boolean(pending[session.value]));
const chatIsProcessing=computed(()=>chatProcessing.value||Boolean(chatPending[session.value]));
const previewIdentity=computed(()=>homePreviewIdentity(preview.value));
function publish(id:string,task:HomePreview|null){
 if(props.workbench&&!checkDay())return;
 if(task&&task.session_id!==id)throw new Error('话题与草案归属不一致，请重新读取');
 slots[id]={task,revision:++slotSequence};
 if(session.value===id){preview.value=task;workloadCandidate.value=task?.workload_candidate??null;previewUncertain.value=false;}
}
let generation=0, controller:AbortController|undefined;
const isCancelled=computed(()=>preview.value?.session_id===session.value && preview.value.status==='cancelled' && !previewUncertain.value);
const usablePreview=computed(()=>preview.value?.session_id===session.value && preview.value.status==='ready' && !preview.value.context.workload_pending && !previewUncertain.value && !topicPending.value && coherentHomePreview(preview.value));
const canConfirm=computed(()=>!manualEditing.value && !props.readOnly && !props.formalPaper && !topicLoading.value && !topicFailure.value && !busy.value && !selectionDirty.value && usablePreview.value && !!homePaperCount(preview.value?.draft) && !preview.value?.receipt);
const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
async function ensureSession(token:number){
 if(!checkDay())return null;
 const requestedDay=day.value;
 const current=session.value;
 if(current)return current;
  const row=await createChatSession(props.workbench?homeDayTitle(requestedDay):'首页推荐调整','builtin',{purpose:props.workbench?'study':'qa'});
 if(token!==generation)return null;
 if(props.workbench&&requestedDay!==homeStudyDay()){checkDay();return null;}
 session.value=row.session_id;sessions.value=[row,...sessions.value.filter(s=>s.session_id!==row.session_id)];rememberSession(row.session_id);
 return row.session_id;
}
 async function refreshHistory(id:string, token:number){const rows=await fetchChatMessages(id,props.workbench?'study':'qa');if((!props.workbench||checkDay())&&token===generation&&session.value===id)history.value=rows;}
async function selectSession(id:string){
 if(!id)return;
 resetOperationUi();
 const wasCurrent=session.value===id, priorInput=input.value;
 const trustedDay=props.workbench&&(localStorage.getItem(homeDayKey(day.value))===id||sessions.value.some(s=>s.session_id===id&&s.title===homeDayTitle(day.value)));
 const token=++generation;controller?.abort();creatingTopic.value=false;topicLoading.value=true;topicFailure.value='';busy.value=true;error.value='';systemEditError.value='';preview.value=null;previewUncertain.value=false;history.value=[];input.value='';selectionDirty.value=false;session.value=id;
 const readRevision=slots[id]?.revision??0;
  try{if(!props.workbench)rememberSession(id);const [task,rows]=await Promise.all([recoverHomePreview(id),fetchChatMessages(id,props.workbench?'study':'qa')]);if(token===generation){
  if(props.workbench&&((sessions.value.some(s=>s.session_id===id&&s.title.startsWith('首页学习 ')&&s.title!==homeDayTitle(day.value)))||(task&&task.context.study_date!==day.value)||(!task&&!trustedDay))){session.value='';preview.value=null;history.value=[];return;}
  if(props.workbench)rememberSession(id);
  if(task&&task.session_id!==id)throw new Error('话题与草案归属不一致，请重新读取');
  const restored=(slots[id]?.revision??0)>readRevision?slots[id].task:task;
   publish(id,restored);history.value=rows;
   if(!sessions.value.some(s=>s.session_id===id))sessions.value=[{session_id:id,title:'首页推荐调整',mode:'builtin',purpose:props.workbench?'study':'qa'},...sessions.value];
 }}catch(e){if(token===generation){if(props.workbench&&isAccessForbidden(e)){clearForbiddenStudyBinding(id);if(wasCurrent)input.value=priorInput;}else{topicFailure.value=errorText(e);error.value=errorText(e);}}}finally{if(token===generation){topicLoading.value=false;busy.value=false;selectionDirty.value=false;}}
}
async function newTopic(){
 resetOperationUi();
 const token=++generation;controller?.abort();topicLoading.value=false;topicFailure.value='';session.value='';preview.value=null;previewUncertain.value=false;history.value=[];input.value='';error.value='';systemEditError.value='';selectionDirty.value=false;busy.value=true;creatingTopic.value=true;localStorage.removeItem(storageKey);
 try{await ensureSession(token);}catch(e){if(token===generation)error.value=errorText(e);}finally{if(token===generation){creatingTopic.value=false;busy.value=false;selectionDirty.value=false;}}
}
async function prepare(action='adjust',useSystem=false,minuteOverride?:number){
 if(!checkDay()||props.readOnly||props.formalPaper||busy.value||topicPending.value||topicLoading.value||topicFailure.value)return false;
 if(action!=='restore')restoreNotice.value='';
 const token=++generation;busy.value=true;error.value='';const goal=action==='adjust'?input.value:'';
 const chatRequest=action==='adjust'&&!!goal.trim();
 chatProcessing.value=chatRequest;
 if(!chatRequest)systemEditError.value='';
 selectionDirty.value=false;
 // Pending or unknown results cannot be confirmed. A definitive failure may
 // restore only the server-returned previous task or retained system snapshot.
 const previous=preview.value;previewUncertain.value=!!previous;
 let requestSession='', requestId=0;
 try{
  const id=await ensureSession(token);if(!id||token!==generation)return false;requestSession=id;requestId=++requestSequence;pending[id]=requestId;if(chatRequest)chatPending[id]=requestId;const task=await adjustHomePreview({session_id:id,request_key:crypto.randomUUID(),goal,action,
   ...(action==='default'?{selected_kp_ids:useSystem?systemSnapshot.value?.recommendations.map(r=>r.kp_id):props.selectedKpIds,budget_minutes:minuteOverride??(useSystem?90:({light:45,standard:90,deep:120} as Record<string,number>)[props.budget]??90)}:{}),expected_version:previous?.draft_version});
  if(pending[id]!==requestId)return false;
  if('kind' in task){
   if(task.session_id!==id)throw new Error('当天聊天归属不一致，请重新读取');
   if(session.value===id){previewUncertain.value=false;if(chatRequest){input.value='';await refreshHistory(id,generation);}}return false;
  }
  if(task.fallback_preview){
   if(task.fallback_preview.session_id!==id)throw new Error('原方案归属不一致，请读取当前状态');
   publish(id,{...task.fallback_preview,...(task.context.workload_pending?{workload_candidate:task}:{adjustment_error:task.message,adjustment_origin:chatRequest?'chat':'system'})});
  }else publish(id,task);
  if(session.value===id&&chatRequest){input.value='';sessions.value=sessions.value.map(s=>s.session_id===id&&s.title==='首页推荐调整'?{...s,title:goal}:s);await refreshHistory(id,generation);}
  return token===generation&&session.value===id&&task.status==='ready'&&!task.fallback_preview&&!task.context.workload_pending;
 }catch(e){if(token===generation||(requestSession===session.value&&pending[requestSession]===requestId)){previewUncertain.value=true;if(chatRequest)error.value=errorText(e)+'。请读取当前状态后重新调整；不会自动重复提交。';else systemEditError.value=errorText(e)+'。选择已保留，请读取当前方案后重试。';}return false;}
 finally{if(requestSession&&pending[requestSession]===requestId)delete pending[requestSession];if(requestSession&&chatPending[requestSession]===requestId)delete chatPending[requestSession];if(token===generation){chatProcessing.value=false;busy.value=false;}}
}
async function restoreState(){if(session.value)await selectSession(session.value);else if(props.workbench)await restoreDaily();}
async function changeDifficulty(direction:'harder'|'easier'){
 if(!checkDay()||busy.value||difficultyBusy.value||props.readOnly||props.formalPaper)return;
 if(!preview.value){
  const prepared=await prepare('default');
  if(!prepared||!preview.value)return;
 }
 if(!preview.value||preview.value.receipt||isCancelled.value)return;
 const id=session.value,taskId=preview.value.task_id;
 difficultyBusy.value=true;difficultyNotice.value='';
 try{
  const result=await adjustHomeDifficulty(taskId,{session_id:id,direction,request_key:crypto.randomUUID()});
  if(session.value!==id)return;
  publish(id,result);
  const count=result.difficulty_change_count??0;
  difficultyNotice.value=count
    ?`已替换 ${count} 道题：${direction==='harder'?'提高':'降低'}难度；题量、知识点覆盖与时间预算保持不变。`
    :'没有可替换的相邻难度题，整卷保持不变。';
 }catch(e){difficultyNotice.value=errorText(e);}
 finally{difficultyBusy.value=false;}
}
function requiredTransitions(task:HomePreview){
 // Current servers report the allocated leaves; keep recommendation flags only
 // as a compatibility fallback when that metadata is absent.
 return [...new Set(task.context.required_graduation_set_transition_ids??task.context.system_recommendations.filter(r=>r.requires_graduation_set_confirmation&&task.draft?.selected_kp_ids.includes(r.kp_id)).map(r=>r.kp_id))].sort();
}
async function confirm(){
 if(!checkDay())return;
 const task=preview.value;if(!canConfirm.value||!task?.draft_version)return;
 const workload=task.context.workload;
 if(workload?.requires_confirmation&&!task.context.workload_accepted&&!window.confirm(`追加后共${homePaperCount(task.draft)}道，预计${workload.effective_budget_minutes}分钟，比原预算多${workload.extra_minutes}分钟。题量较大，是否继续生成？`))return;
 const ids=requiredTransitions(task);
 if(ids.length&&!window.confirm('这些知识点将开始新的考核题集，历史作答仍保留。是否继续？'))return;
 busy.value=true;confirming.value=true;error.value='';const token=generation;
 try{
  const displayed=homePreviewIdentity(task);
  const live=await recoverHomePreview(task.session_id);
  if(token!==generation||displayed!==previewIdentity.value||selectionDirty.value)return;
  if(!coherentHomePreview(live)||homePreviewIdentity(live)!==displayed||JSON.stringify(live?.draft)!==JSON.stringify(task.draft)||JSON.stringify(requiredTransitions(live!))!==JSON.stringify(ids))throw new Error('预览已更新或已失效，请读取最新预览后重新确认');
  const result=await confirmHomePreview(task.task_id,{session_id:task.session_id,draft_version:task.draft_version,confirm_legacy_set_transition_ids:ids,...(workload?.requires_confirmation?{accept_workload_increase:true}:{})});
  if(token!==generation)return;publish(task.session_id,result);emit('confirmed');
 }
 catch(e){if(token===generation){previewUncertain.value=true;error.value=errorText(e)+'。请读取状态核对回执，未确认成功前不会显示生成成功。';}}
 finally{if(token===generation){busy.value=false;confirming.value=false;}}
}
async function send(){
 if(!checkDay()||!input.value.trim()||busy.value||topicPending.value)return;
 if(props.workbench&&/^(?:我确定|我确认|我同意|好的|好|继续|确认|确定)[。！!]?$/u.test(input.value.trim())){error.value=pendingWorkload.value?'请点击方案卡片中的“接受此方案”或“返回调整”，不会重新匹配知识点。':'请在系统推荐区域点击“确定生成试卷”，聊天只调整当前方案。';return;}
 if(props.workbench&&/^接受(?:这个|此)?方案[。！!]?$/u.test(input.value.trim())){if(pendingWorkload.value){await decideWorkload(true);input.value='';}else error.value='当前没有唯一待接受方案。';return;}
 if(props.workbench&&/^返回调整[。！!]?$/u.test(input.value.trim())){if(pendingWorkload.value)await decideWorkload(false);else await beginScopeEdit();input.value='';return;}
 if(mode.value==='adjust'){await prepare();return;}
 const token=++generation;busy.value=true;chatProcessing.value=true;error.value='';controller=new AbortController();let failure='';
  try{const id=await ensureSession(token);if(!id||token!==generation)return;await streamChatAnswer(id,input.value,(_event,data)=>{if(_event==='error')failure=String(data.message??'回答失败');},controller.signal,{purpose:props.workbench?'study':'qa'});if(token===generation){input.value='';await refreshHistory(id,token);if(failure)error.value=failure;}}
 catch(e){if(token===generation)error.value=errorText(e);}finally{if(token===generation){busy.value=false;chatProcessing.value=false;}}
}

const consumed=computed(()=>Boolean(preview.value?.receipt));
const anotherConfirmedPaper=computed(()=>!!props.formalPaper&&!!preview.value?.receipt&&preview.value.receipt.plan_id!==props.formalPaper.plan_id);
const displayedPaper=computed(()=>{
 const p=preview.value;
 if(!p?.draft||p.session_id!==session.value||p.context.study_date!==day.value)return null;
 // Keep the last coherent server-confirmed preview visible while a newer
 // request is pending or its result is unknown. Confirmation remains disabled
 // by usablePreview/canGenerate until the server state is recovered.
 return coherentHomePreview({...p,status:p.receipt?'ready':p.status}) ? p.draft : null;
});
const retainedBaseline=computed(()=>{
 const p=preview.value,d=p?.retained_baseline;
 return p&&p.session_id===session.value&&p.context.study_date===day.value&&['failed','needs_info'].includes(p.status)&&!p.receipt&&d&&coherentHomePaper(d,d.budget_minutes)?d:null;
});
const recommendedPaper=computed(()=>displayedPaper.value??retainedBaseline.value??(!preview.value&&!topicLoading.value&&!topicFailure.value&&!systemError.value?systemSnapshot.value?.initial_paper:null));
function eligibleQuestionLabel(id:string){
 const inventories=[preview.value?.context.inventory,systemSnapshot.value?.inventory];
 for(const inventory of inventories){
  const node=inventory?.recommendation_nodes?.find(item=>item.kp_id===id);
  if(node&&Number.isInteger(node.practice_eligible_count))return `${node.practice_eligible_count}道可用题`;
 }
 return '可用题量暂未读取';
}
const canGenerate=computed(()=>!manualEditing.value&&!props.readOnly&&!props.formalPaper&&!consumed.value&&!busy.value&&!generatingPaper.value&&!topicPending.value&&!topicLoading.value&&!topicFailure.value&&!previewUncertain.value&&!selectionDirty.value&&(canConfirm.value||!!retainedBaseline.value||(!preview.value&&!systemLoading.value&&!systemError.value&&!!homePaperCount(systemSnapshot.value?.initial_paper))));
const recommendationView=computed<HomeSystemRecommendation|null>(()=>{
 const p=preview.value,d=displayedPaper.value??retainedBaseline.value;
 if(d&&p){
  const known=new Map([...(systemSnapshot.value?.recommendations??[]),...p.context.system_recommendations].map(r=>[r.kp_id,r]));
  const recommendations=[...new Set([...d.questions.map(q=>q.kp_id),...d.selected_kp_ids])].filter(id=>d.selected_kp_ids.includes(id)).map(id=>{
   const q=d.questions.find(q=>q.kp_id===id)??p.context.baseline?.questions.find(q=>q.kp_id===id);
   const saved=d.scope_nodes?.find(n=>n.kp_id===id),unavailable=p.context.unavailable_nodes?.find(n=>n.kp_id===id);
   const original=known.get(id),count=homeNodeCount(d,id);
   return {kp_id:id,name:saved?.name??original?.name??q?.kp_name??unavailable?.name??'无法读取名称，请重新读取方案',reason:original?.reason??'adjusted',next_step:count?original?.next_step??`本方案选入 ${count} 道真实题。`:saved?.allocation_reason??'暂无合格题目',requires_graduation_set_confirmation:original?.requires_graduation_set_confirmation??false};
  });
  return {recommendations,inventory:p.context.inventory,initial_paper:d,evidence:p.context.evidence,blockers:[],note:systemSnapshot.value?.note??''};
 }
 return systemSnapshot.value;
});
function paperKey(p:HomePaper|null|undefined){return p?JSON.stringify([p.selected_kp_ids,p.budget_minutes,p.total_minutes,p.selection_fingerprint??p.questions.map(q=>[q.question_id,q.question_version_id,q.minutes])]):'';}
const restoreBaseline=computed(()=>preview.value?.context.baseline??systemSnapshot.value?.initial_paper??null);
const canRestoreSystemRecommendation=computed(()=>!props.readOnly&&!props.formalPaper&&!busy.value&&!topicLoading.value&&!topicFailure.value
 &&Boolean(homePaperCount(restoreBaseline.value)));
const canUndoRecommendation=computed(()=>!props.readOnly&&!props.formalPaper&&!busy.value&&!topicLoading.value
 &&preview.value?.session_id===session.value&&preview.value.status==='ready'&&!preview.value.receipt&&Boolean(preview.value.undo_available));
const canRedoRecommendation=computed(()=>!props.readOnly&&!props.formalPaper&&!busy.value&&!topicLoading.value
 &&preview.value?.session_id===session.value&&preview.value.status==='ready'&&!preview.value.receipt&&Boolean(preview.value.redo_available));
async function historyAction(action:'undo'|'redo'){
 if(action==='undo'?!canUndoRecommendation.value:!canRedoRecommendation.value)return;
 await prepare(action);
}
async function restoreSystemRecommendation(){
 if(!canRestoreSystemRecommendation.value)return;
 const baseline=restoreBaseline.value;
 if(!baseline)return;
 const current=preview.value;
 if(current?.status==='ready'&&!current.receipt&&!previewUncertain.value&&current.session_id===session.value
   &&paperKey(current.draft)===paperKey(baseline)){
  restoreNotice.value='当前方案已经是今日系统推荐。';
  return;
 }
 restoreNotice.value='';
 const restored=await prepare('restore');
 if(restored)restoreNotice.value='已恢复今日系统推荐。';
}
const pendingWorkload=computed(()=>{
 const p=workloadCandidate.value;
 return p&&p.session_id===session.value&&p.context.study_date===day.value&&p.context.workload_pending&&!previewUncertain.value&&!topicLoading.value&&!topicFailure.value&&coherentHomePreview(p)?p:null;
});
async function decideWorkload(accept:boolean){
 const candidate=pendingWorkload.value;
 if(!candidate||busy.value||!checkDay())return;
 if(Date.parse(candidate.context.expires_at)<=Date.now()){error.value='这份方案已过期，请读取当前状态后重新调整。';return;}
 const token=generation;busy.value=true;workloadDeciding.value=true;error.value='';
 try{
  const result=await adjustHomePreview({session_id:candidate.session_id,request_key:crypto.randomUUID(),goal:'',
   action:accept?'accept_workload':'dismiss_workload',target_task_id:candidate.task_id,expected_version:candidate.draft_version});
  if(token!==generation||session.value!==candidate.session_id)return;
  if('kind' in result)throw new Error('方案状态异常，请读取当前状态');
  publish(candidate.session_id,result);
 }catch(e){if(token===generation){previewUncertain.value=true;error.value=errorText(e)+'。请读取当前状态核对结果。';}}
 finally{if(token===generation){busy.value=false;workloadDeciding.value=false;}}
}
const isSystemAdjustment=computed(()=>preview.value?.adjustment_origin==='system'||(!preview.value?.adjustment_origin&&preview.value?.context.request_origin==='system'));
const hasAdjustmentFailure=computed(()=>Boolean(preview.value?.adjustment_error||preview.value&&['failed','needs_info'].includes(preview.value.status)));
const adjustmentFailure=computed(()=>!isSystemAdjustment.value&&hasAdjustmentFailure.value);
const systemEditNotice=computed(()=>systemEditError.value||(isSystemAdjustment.value&&hasAdjustmentFailure.value?(recommendedPaper.value?'知识点调整未成功，原方案已保留。':'知识点调整未成功，请重新选择范围。'):''));
const shortFailure=computed(()=>{
 const notice=preview.value?.adjustment_error??(preview.value&&['failed','needs_info'].includes(preview.value.status)?preview.value.message:'');
 if(!notice)return '该次题库检索失败。';
 if(notice&&!/检索失败|查询失败|异常|服务暂时|参数校验|错误编号/.test(notice))return notice;
 return recommendedPaper.value?'加入失败，原系统推荐已保留。':'新增题目暂时无法加入，请重试。';
});
const dailyMessages=computed(()=>{
 const messages=history.value.map(m=>({...m,content:m.role==='assistant'&&(/真实题库检索失败|不会转为通用知识回答/.test(m.content)||m.content===preview.value?.adjustment_error)?shortFailure.value:m.content}));
 if(adjustmentFailure.value&&messages.at(-1)?.content!==shortFailure.value)messages.push({message_id:'current-adjustment-notice',role:'assistant',content:shortFailure.value});
 return messages;
});
async function generateCurrent(){
 if(!checkDay()||!canGenerate.value)return;
 if(canConfirm.value){await confirm();return;}
 const restoring=!!retainedBaseline.value;
 const shown=paperKey(retainedBaseline.value??systemSnapshot.value?.initial_paper),token=generation;
 generatingPaper.value=true;
 try{
  await prepare(restoring?'restore':'default',true);
  if(generation!==token+1||!usablePreview.value||!preview.value?.draft)return;
  if(paperKey(preview.value.draft)!==shown){error.value='推荐已更新，已展示最新方案。请核对题目后再次点击确定生成试卷。';return;}
  await confirm();
 }finally{generatingPaper.value=false;}
}
async function ask(){
 if(props.readOnly||props.formalPaper)return;
 await send();
}

onMounted(()=>{if(typeof document!=='undefined')document.addEventListener?.('keydown',onEscape);});
onBeforeUnmount(()=>{if(typeof document!=='undefined')document.removeEventListener?.('keydown',onEscape);});
onMounted(async()=>{if(props.workbench){void loadSystem();dayTimer=setInterval(checkDayOnFocus,30000);if(typeof window!=='undefined')window.addEventListener('focus',checkDayOnFocus);await restoreDaily();return;}const token=generation;try{const rows=await listChatSessions('builtin','qa');if(token!==generation)return;sessions.value=rows;const id=localStorage.getItem(storageKey);if(id)await selectSession(id);}catch(e){error.value=errorText(e);}});
onBeforeUnmount(()=>{if(dayTimer)clearInterval(dayTimer);if(typeof window!=='undefined')window.removeEventListener('focus',checkDayOnFocus);generation++;systemGeneration++;controller?.abort();});
// Scope edits are submitted explicitly; prop restoration must not issue preview writes.
watch(()=>history.value.length,async()=>{await nextTick();dailyChat.value?.scrollTo({top:dailyChat.value.scrollHeight,behavior:'smooth'});});
defineExpose({prepare});
</script>
<template>
 <section v-if="workbench" class="simple-workspace" :class="{'chat-open':chatOpen}" data-testid="home-recommendation-assistant" :data-preview-id="preview?.task_id" :data-home-ui-revision="homeUiRevision" aria-label="今日学习工作台">
  <section v-if="manualEditing" ref="scopeEditor" tabindex="-1" role="dialog" aria-modal="true" class="scope-edit-panel" data-testid="home-scope-editor" aria-label="调整知识点" @keydown.esc.stop="cancelScopeEdit">
   <header><h2>调整知识点</h2></header>
   <fieldset class="scope-edit-body" :disabled="scopeSaving"><slot name="manual-controls"><section><h3>当前已选知识点（{{selectedKpIds.length}}）</h3><ul><li v-for="id in selectedKpIds" :key="id">{{recommendationView?.recommendations.find(n=>n.kp_id===id)?.name??'知识点名称待加载'}}<button type="button" @click="toggleManualKp(id)">移除</button></li></ul></section></slot></fieldset>
   <p v-if="systemEditNotice" role="alert" data-testid="home-system-edit-error">{{systemEditNotice}}</p>
   <footer><span>已选 {{selectedKpIds.length}} 个知识点</span><button type="button" aria-label="完成并保存调整" :disabled="busy||scopeSaving||topicLoading||!selectedKpIds.length" @click="applyScopeEdit">{{scopeSaving?'保存中…':'完成'}}</button><button type="button" :disabled="scopeSaving" @click="cancelScopeEdit">取消</button></footer>
  </section>
  <template v-else>
  <p class="simple-overview" data-testid="home-overview">{{recommendationView ? recommendationView.recommendations.length : '—'}} 个知识点 · {{recommendationView?.inventory?.practice_eligible_count??'—'}} 道可用题 · 本方案安排 {{recommendationView ? homePaperCount(recommendationView.initial_paper) : '—'}} 道 · 预计 {{recommendationView?.initial_paper?.total_minutes??'—'}} 分钟 / 预算 {{preview?.context.workload?.requested_budget_minutes??recommendedPaper?.budget_minutes??90}} 分钟</p>
  <p v-if="preview?.context.workload&&!preview.context.workload_pending" role="status">当前方案预计 {{preview.context.workload.effective_budget_minutes}} 分钟，比建议预算多 {{preview.context.workload.extra_minutes}} 分钟。</p>
  <div class="simple-recommendation-row">
    <section class="simple-recommendations" data-testid="home-recommendation-list"><header class="recommendation-list-heading"><h2>系统推荐知识点</h2><button ref="chatLauncher" type="button" class="home-chat-launcher" aria-controls="home-daily-panel" :aria-expanded="chatOpen" @click="openChat">询问奶蛙<span v-if="chatIsProcessing"> · 处理中</span><span v-else-if="pendingWorkload"> · 待确认</span><span v-else-if="error||adjustmentFailure"> · 查看提示</span></button><button ref="scopeLauncher" type="button" :disabled="readOnly||!!formalPaper" @click="beginScopeEdit">调整知识点</button><button type="button" data-testid="undo-home-recommendation" :disabled="!canUndoRecommendation" @click="historyAction('undo')">撤销</button><button type="button" data-testid="redo-home-recommendation" :disabled="!canRedoRecommendation" @click="historyAction('redo')">重做</button><button type="button" data-testid="restore-home-recommendation" :disabled="!canRestoreSystemRecommendation" @click="restoreSystemRecommendation">恢复今日系统推荐</button></header>
   <HomeRecommendationBaseline compact :snapshot="recommendationView" :loading="systemLoading&&!displayedPaper" :error="displayedPaper?'':systemError" @reload="loadSystem"/>
   <p v-if="restoreNotice" role="status" data-testid="home-restore-notice">{{restoreNotice}}</p><p class="recommendation-status" role="status">{{consumed||formalPaper?'已生成试卷':displayedPaper?'已调整，待确认':retainedBaseline?'系统推荐，待确认':preview?.status==='failed'?'调整失败，尚无可确认方案':preview&&!displayedPaper?'需要重新调整方案':'系统初案'}}</p>

  <div v-if="!readOnly&&!formalPaper" class="paper-generate-action"><button type="button" class="primary" data-testid="confirm-home-paper" :data-preview-id="preview?.task_id" :data-preview-version="preview?.draft_version" :disabled="!canGenerate" @click="generateCurrent">{{generatingPaper||confirming?'正在核对并生成…':'确定生成试卷'}}</button></div>
  <div v-if="readOnly||formalPaper" class="simple-primary-actions"><button type="button" class="primary" @click="emit('practice')">开始练习</button><button type="button" data-testid="confirm-home-paper" :disabled="true">确定生成试卷</button></div>
</section>
   <aside v-show="chatOpen" id="home-daily-panel" class="simple-frog" role="region" aria-label="奶蛙每日聊天" data-testid="home-frog-adjustment" @keydown.esc.stop="closeChat"><header><StudyMascot pose="read"/><h2>和奶蛙聊聊</h2><button type="button" class="home-chat-close" aria-label="关闭奶蛙聊天" @click="closeChat">关闭</button></header>

  <p v-if="formalPaper" class="simple-notice" data-testid="confirmed-paper-banner">已确认的正式试卷：{{formalPaper.total_count}} 道 / {{formalPaper.estimated_minutes}} 分钟。此处仅回看推荐与当天记录，不会重新生成或覆盖正式卷。</p>

  <div class="daily-chat-day">{{day}} · 今日聊天</div>
  <section class="home-daily-chat" ref="dailyChat" tabindex="-1" data-testid="home-daily-chat" aria-label="今日聊天记录" aria-live="polite">
   <p v-if="topicLoading" role="status">正在恢复今天的聊天…</p><p v-else-if="!history.length&&!busy&&!topicPending" class="daily-chat-empty">今天想怎么练？</p>
   <article v-for="m in dailyMessages" :key="m.message_id" :class="['daily-message',m.role==='user'?'daily-message--user':'daily-message--assistant']"><b>{{m.role==='user'?'我':'奶蛙'}}</b><HomeFormulaContent :text="m.content"/></article>
   <p v-if="chatIsProcessing" role="status">奶蛙正在核对推荐与题库…</p>
  </section>
  <section v-if="pendingWorkload?.draft&&pendingWorkload.context.workload" class="workload-choice" role="status" data-testid="home-workload-choice" :data-preview-id="pendingWorkload.task_id" :data-preview-version="pendingWorkload.draft_version">
   <h3>确认追加方案</h3>
   <p>当前题量：{{homePaperCount(pendingWorkload.draft)}} 道 · 原预算：{{pendingWorkload.context.workload.requested_budget_minutes}} 分钟</p>
   <p>预计耗时：{{pendingWorkload.draft.total_minutes}} 分钟 · 超过建议预算 {{pendingWorkload.context.workload.extra_minutes}} 分钟</p>
   <p>原题完整保留。接受只更新方案，随后再点击首页的“确定生成试卷”。</p>
   <div class="home-actions"><button type="button" :disabled="busy||workloadDeciding||topicLoading" @click="decideWorkload(true)">接受此方案</button><button type="button" :disabled="busy||workloadDeciding||topicLoading" @click="decideWorkload(false)">返回调整</button></div>
  </section>
  <p v-if="preview?.context.workload_accepted" role="status" data-testid="home-workload-accepted">方案已接受，可以生成试卷。</p>
  <form v-if="!readOnly&&!formalPaper" class="simple-composer" @submit.prevent="ask">
   <div class="home-chat-mode"><label><input v-model="mode" type="radio" value="adjust"/>调整方案</label><label><input v-model="mode" type="radio" value="qa"/>自由提问</label></div>
   <label class="sr-only" for="home-goal">调整学习方案</label><textarea id="home-goal" v-model="input" :disabled="busy||topicPending||generatingPaper" placeholder="告诉奶蛙你想怎么调整……"/>
   <div class="simple-primary-actions"><button type="submit" :disabled="busy||topicPending||generatingPaper||!input.trim()">发送</button></div>
  </form>

  <p v-if="systemError&&displayedPaper" role="alert">{{systemError}} 已恢复的当前方案独立保留。<button @click="loadSystem">重试初案读取</button></p>
  <p v-if="error&&!topicFailure" role="alert">{{error}} <button :disabled="busy||topicPending" @click="restoreState">读取当前状态 / 核对回执</button></p>

   </aside>
  </div>
  <p v-if="scopeDelta" class="scope-change-summary" role="status">保留：{{scopeDelta.retained.join('、')||'无'}}；移除：{{scopeDelta.removed.join('、')||'无'}}；新增：{{scopeDelta.added.join('、')||'无'}}。</p>
  <p v-if="systemEditNotice" role="alert" data-testid="home-system-edit-error">{{systemEditNotice}}<button v-if="systemEditError" :disabled="busy||topicPending" @click="restoreState">读取当前方案</button></p>
  <p v-for="node in preview?.context.unavailable_nodes??[]" :key="node.kp_id" role="status">{{node.name}}：{{node.reason}}</p>
  <section class="simple-paper-state" aria-live="polite">
   <p v-if="topicLoading||topicPending" role="status" data-testid="topic-loading">正在恢复今天的聊天与有效方案…</p>
   <div v-else-if="topicFailure" role="alert">聊天恢复失败：{{topicFailure}} <button @click="restoreState">重试恢复</button></div>
   <p v-else-if="consumed" data-testid="confirmed-workspace-state">{{anotherConfirmedPaper?'这是其他试卷的已确认记录，不等同于当前正式卷。':'已生成正式试卷。这是已确认的方案记录，不是待确认草案。'}}</p>
   <p v-else-if="formalPaper">今日聊天{{preview?'包含未确认的历史预览':'没有可恢复预览'}}，它不等同于已确认的正式试卷；本页不执行再次确认。</p>
   <p v-else-if="isCancelled" role="status">预览已取消，旧方案不能确认；可以调整知识点重新准备方案。</p>
   <p v-else-if="previewUncertain" role="status">操作结果尚未核实，页面保留最后一份有效方案供查看；确认前请读取当前状态。</p>
   <p v-if="!preview&&!topicLoading&&!topicPending&&!topicFailure">尚未生成正式试卷。你可以直接采用系统推荐，也可以先询问奶蛙调整。</p>
    <div v-if="!preview&&recommendedPaper&&!topicLoading&&!topicPending&&!topicFailure" class="home-actions">
      <button type="button" data-testid="home-difficulty-harder" :disabled="busy||difficultyBusy" @click="changeDifficulty('harder')">{{difficultyBusy?'调整中…':'提高难度'}}</button>
      <button type="button" data-testid="home-difficulty-easier" :disabled="busy||difficultyBusy" @click="changeDifficulty('easier')">降低难度</button>
    </div>
    <p v-if="difficultyNotice" class="home-difficulty-notice" role="status" data-testid="home-difficulty-notice">{{difficultyNotice}}</p>
   <section v-if="displayedPaper&&preview" data-testid="home-current-summary" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :data-session-id="session"><section data-testid="home-paper-detail" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :data-preview-key="previewIdentity" aria-label="学习安排摘要"><p>当前安排 {{homePaperCount(displayedPaper)}} 道，预计 {{displayedPaper.total_minutes}} 分钟。具体题目请到正式卷中查看。</p></section></section>
    <div v-if="displayedPaper&&preview&&!preview.receipt" class="home-actions">
      <button type="button" data-testid="home-difficulty-harder" :disabled="busy||difficultyBusy" @click="changeDifficulty('harder')">{{difficultyBusy?'调整中…':'提高难度'}}</button>
      <button type="button" data-testid="home-difficulty-easier" :disabled="busy||difficultyBusy" @click="changeDifficulty('easier')">降低难度</button>
    </div>
    <p v-if="difficultyNotice" class="home-difficulty-notice" role="status" data-testid="home-difficulty-notice">{{difficultyNotice}}</p>
  </section>


  </template>
 </section>

 <section v-else class="home-frog" :class="{'home-frog--workbench':workbench}" data-testid="home-recommendation-assistant" :data-preview-id="preview?.task_id" :data-home-ui-revision="homeUiRevision" aria-label="奶蛙调整系统推荐">
  <header><StudyMascot pose="read"/><div><h2>和奶蛙一起调整推荐</h2><p>从现有题库选题，先预览，再确认。</p></div></header>
  <HomeRecommendationBaseline v-if="workbench" :snapshot="systemSnapshot" :loading="systemLoading" :error="systemError" @reload="loadSystem" @use="prepare('default',true)"/>
  <div :class="{'home-workbench-columns':workbench}">
  <section :class="{'home-workbench-adjustment':workbench}" aria-label="奶蛙调整学习需求">
   <header v-if="workbench" class="workbench-panel-heading"><span>02 · 奶蛙调整</span><h3>说说你想怎么练</h3><p>范围、时间和题量都可以调整；自由提问不会创建练习。</p></header>
  <div class="home-actions"><button :disabled="busy||topicPending" @click="prepare('default')">查看所选范围的推荐预览</button><button :disabled="creatingTopic||confirming" @click="newTopic">新话题</button></div>
  <label>当前话题<select :value="session" :data-session-id="session" :disabled="creatingTopic||confirming" @change="selectSession(($event.target as HTMLSelectElement).value)"><option value="" disabled :selected="!session">{{creatingTopic?'正在创建新话题…':'选择已有话题，或直接开始新话题'}}</option><option v-for="s in sessions" :key="s.session_id" :value="s.session_id" :selected="s.session_id===session">{{s.title}} · {{s.session_id.slice(0,6)}}</option></select></label>

  <form @submit.prevent="send"><div class="home-mode-switch"><label><input v-model="mode" type="radio" value="adjust"/>调整试卷</label><label><input v-model="mode" type="radio" value="qa"/>自由提问（不调整试卷）</label></div><label class="home-goal">学习需求<textarea v-model="input" :disabled="busy||topicPending" placeholder="例如：我想练线性代数，安排90分钟；或者把刚才的90分钟改成60分钟。"/></label><div class="home-actions"><button :disabled="busy||topicPending||!input.trim()" type="submit">{{busy?'正在核对真实题库…':'发送'}}</button></div></form>
  <p v-if="error" role="alert">{{error}}</p><button v-if="error" :disabled="busy||topicPending" @click="restoreState">读取当前状态 / 核对回执</button>
  <details v-if="history.length" :open="mode==='qa'" class="home-history" aria-label="对话历史"><summary>历史对话（不可确认；当前方案见预览卡）</summary><article v-for="m in history" :key="m.message_id"><b>{{m.role==='user'?'我':'奶蛙'}}</b><MarkdownContent :text="m.content"/></article></details>
  <details v-if="workbench" class="manual-controls"><summary>手动微调范围与建议预算</summary><slot name="manual-controls"/></details>
  </section>
  <section :class="{'home-workbench-result':workbench}" aria-label="调整后的试卷方案">
   <header v-if="workbench" class="workbench-panel-heading"><span>03 · 当前试卷</span><h3>先看清安排，再开始作答</h3></header>
   <div v-if="workbench&&!preview" class="workbench-empty" data-testid="workbench-empty"><strong>尚无待确认试卷</strong><p>读取系统初案后开始预览，或在上方告诉奶蛙新的范围和预算。预览不等于正式试卷，确认前不会入卷。</p><button :disabled="busy||topicPending||systemLoading||!!systemError||!homePaperCount(systemSnapshot?.initial_paper)" @click="prepare('default',true)">查看系统初案的题目预览</button></div>
  <section v-if="preview" class="home-current-controls" :data-preview-id="preview.task_id" :data-preview-key="previewIdentity">
   <section data-testid="home-current-summary" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :data-session-id="session">
    <h3>本次待确认安排</h3>
    <p v-if="usablePreview&&preview.draft">{{homePaperCount(preview.draft)}} 道 · {{preview.draft.total_minutes}} 分钟 · 预算 {{preview.budget_minutes}} 分钟</p>
    <p v-else-if="topicPending" role="status">当前话题仍在更新预览，请等待完成后查看；不能确认旧方案。</p>
    <p v-else-if="isCancelled">预览已取消</p><p v-else>预览不可确认，请读取当前状态。</p>
    <small>预览 {{preview.task_id}}</small>
   </section>
   <div class="home-actions"><button type="button" data-testid="home-difficulty-harder" :disabled="busy||difficultyBusy||!usablePreview||!!preview.receipt||isCancelled" @click="changeDifficulty('harder')">{{difficultyBusy?'调整中…':'提高难度'}}</button><button type="button" data-testid="home-difficulty-easier" :disabled="busy||difficultyBusy||!usablePreview||!!preview.receipt||isCancelled" @click="changeDifficulty('easier')">降低难度</button><button data-testid="confirm-home-paper" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :disabled="!canConfirm" @click="confirm">确认并生成这份练习卷<span v-if="usablePreview&&preview.draft">（{{homePaperCount(preview.draft)}}题 / {{preview.draft.total_minutes}}分钟）</span></button><button :disabled="busy||topicPending||!!preview.receipt" @click="prepare('restore')">恢复原系统推荐</button><button :disabled="busy||topicPending||!!preview.receipt||isCancelled" @click="prepare('cancel')">取消预览</button></div>
   <p v-if="difficultyNotice" class="home-difficulty-notice" role="status" data-testid="home-difficulty-notice">{{difficultyNotice}}</p>  </section>
  <section v-if="preview" data-testid="home-paper-preview" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version">
   <div v-if="isCancelled" role="status" data-testid="home-preview-cancelled"><h3>预览已取消</h3><p>这份预览已失效，不能确认；今日卷和作答记录未改变。</p><button type="button" :disabled="busy||topicPending" @click="prepare('default')">重新生成预览</button></div>
   <p v-else-if="previewUncertain" role="status">当前预览暂不可用，请等待操作完成；若请求失败，请读取当前状态核对结果。</p>
   <p v-else>{{preview.message}}</p><section v-if="workbench&&usablePreview&&preview.draft" class="workbench-constraints" data-testid="workbench-constraints"><h4>你的约束 → 当前方案</h4><p>原话：{{preview.goal}}</p><p>预算上限 {{preview.budget_minutes}} 分钟<span v-if="preview.draft.question_limit"> · 题量上限 {{preview.draft.question_limit}} 道</span>；实际 {{homePaperCount(preview.draft)}} 道 / {{preview.draft.total_minutes}} 分钟。</p><p v-if="preview.context.baseline">原方案：{{homePaperCount(preview.context.baseline)}} 道 / {{preview.context.baseline.total_minutes??0}} 分钟（预算 {{preview.context.baseline.budget_minutes}} 分钟）。</p><p>最终范围：{{preview.draft.scope_nodes?.map(n=>`${n.name} · ${eligibleQuestionLabel(n.kp_id)}`).join('、')}}</p></section>
   <template v-if="!isCancelled&&!previewUncertain">
   <details v-if="!workbench"><summary>原推荐对照</summary>
   <h3>系统原推荐知识点</h3><ul><li v-for="r in preview.context.system_recommendations" :key="r.kp_id">{{r.name}}</li></ul>
   <p v-if="preview.context.baseline">原预览 {{homePaperCount(preview.context.baseline)}} 道 · {{preview.context.baseline.total_minutes??0}} 分钟</p>
   </details>
   <template v-if="usablePreview&&preview.draft"><h3>当前试卷预览</h3><p>需求：{{preview.goal}} · 预算 {{preview.budget_minutes}} 分钟；实际 {{homePaperCount(preview.draft)}} 道 / {{preview.draft.total_minutes}} 分钟</p>
    <p v-if="preview.draft.diff">相较原推荐：增加 {{preview.draft.diff.added.length}} 道，移除 {{preview.draft.diff.removed.length}} 道，保留 {{preview.draft.diff.retained.length}} 道。</p>
    <section data-testid="home-paper-detail" :data-preview-id="preview.task_id" :data-preview-version="preview.draft_version" :data-preview-key="previewIdentity" aria-label="学习安排摘要">
      <p data-testid="home-detail-summary">{{homePaperCount(preview.draft)}} 道 · {{preview.draft.total_minutes}} 分钟</p>
      <ul><li v-for="node in preview.draft.scope_nodes??[]" :key="node.kp_id">{{node.name}} · {{eligibleQuestionLabel(node.kp_id)}}：今日安排 {{node.assigned_count}} 道</li></ul>
      <p>确认生成后再查看具体题目。</p>
    </section>
   </template>
   </template>
<p v-if="preview.status!=='ready'&&!preview.receipt">当前预览不可确认，请重新调整。</p>
  </section>
  </section>
  </div>
 </section>
</template>
<style scoped>
.home-frog{padding:1rem;border:1px solid var(--border-color,#d7dfd0);border-radius:1rem;min-width:0}.home-frog header,.home-actions{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}.home-frog header :deep(.study-mascot){width:64px;height:64px}.home-frog h2{font-size:1.2rem}.home-frog textarea{display:block;width:100%;min-height:6rem;box-sizing:border-box;margin:.6rem 0}.home-frog select{max-width:100%}.home-history{max-height:20rem;overflow:auto}.home-frog article,.home-frog li{overflow-wrap:anywhere;margin:.6rem 0}.home-frog small{overflow-wrap:anywhere}.home-actions{margin:.7rem 0}.home-frog button{min-height:2.5rem}.home-frog [role=alert]{color:#b13b20}
.home-paper-detail{box-sizing:border-box;width:100%;min-width:0;padding:1rem;border:1px solid #d7dfd0;border-radius:1rem;margin-block:1rem;text-align:left}.home-paper-detail li{margin-block:1rem;overflow-wrap:anywhere}.home-paper-detail small{overflow-wrap:anywhere}.home-paper-detail :deep(.katex-display){max-width:100%;overflow-x:auto}
.home-current-controls{position:sticky;top:12px;z-index:2;background:var(--surface,#fff);border:1px solid #d7dfd0;border-radius:.7rem;padding:.7rem;margin:.8rem 0;box-shadow:0 2px 8px #0000000b}.home-current-controls small{display:block;overflow-wrap:anywhere}.home-current-controls h3{margin:.2rem 0}.home-current-controls .home-actions{margin-bottom:0}@media(max-width:760px){.home-current-controls{position:static;box-shadow:none}}

.home-frog.home-frog--workbench{border:0;padding:0;text-align:left}.home-frog--workbench>header{display:none}.home-workbench-columns{display:flex;flex-direction:column;gap:20px;margin-top:20px}.home-workbench-adjustment,.home-workbench-result{box-sizing:border-box;width:100%;min-width:0}.home-workbench-adjustment{padding:0 0 20px;border-bottom:1px solid var(--border)}.home-workbench-result{padding:0;background:var(--background)}.workbench-panel-heading{display:block!important;margin-bottom:18px}.workbench-panel-heading span{font-size:12px;color:var(--text-tertiary,#71816c)}.workbench-panel-heading h3{font-size:18px;margin:6px 0}.workbench-panel-heading p{font-size:12px;line-height:1.7}.home-frog--workbench .home-current-controls{position:static;box-shadow:none;background:var(--bg,#f2f5ed)}.home-frog--workbench .home-history{margin-top:20px;max-height:300px}.manual-controls{margin-top:20px;border-top:1px solid var(--border,#d7dfd0);padding-top:16px}.manual-controls summary{cursor:pointer}.home-frog.home-frog--workbench .manual-controls :deep(.study-setup-grid){display:block}.home-frog.home-frog--workbench .manual-controls :deep(.study-setup-layout){padding:0;border:0;margin-top:14px}.home-frog.home-frog--workbench .manual-controls :deep(.study-suggestion-heading){display:none}.home-frog.home-frog--workbench .manual-controls :deep(.study-sheet-title){display:none}.workbench-constraints,.workbench-empty{padding:12px 14px;background:var(--sidebar);border-radius:8px;margin:12px 0}.workbench-constraints p{font-size:13px;line-height:1.8}.home-frog--workbench .home-paper-detail{padding:0;border:0}.home-workbench-result .home-actions button:first-child{background:#4c6955;color:#fff;border-color:#4c6955}@media(max-width:1050px){.home-workbench-columns{grid-template-columns:minmax(0,1fr)}.home-workbench-adjustment,.home-workbench-result{padding:16px}}

.home-mode-switch{display:flex;flex-wrap:wrap;gap:14px;font-size:13px}.home-frog--workbench form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:end}.home-frog--workbench .home-mode-switch{grid-column:1/-1}.home-frog--workbench textarea{min-height:72px;margin-bottom:0}.home-frog--workbench select{box-sizing:border-box;width:min(100%,420px);min-width:0;white-space:normal}.home-frog--workbench .home-current-controls{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:var(--sidebar);border-color:var(--border)}.home-workbench-result .home-paper-detail{padding:0}.home-frog--workbench button{max-width:100%;white-space:normal;overflow-wrap:anywhere}.home-frog--workbench .home-actions{gap:8px}.home-goal{min-width:0}@media(max-width:640px){.home-frog--workbench form{grid-template-columns:minmax(0,1fr)}.home-frog--workbench .home-current-controls{display:block}.home-frog--workbench .home-current-controls .home-actions{display:flex;flex-direction:column;align-items:stretch}.home-workbench-adjustment,.home-workbench-result{padding:0}}

.simple-workspace{min-width:0;max-width:100%;width:100%;height:auto;max-height:none;padding-bottom:max(64px,env(safe-area-inset-bottom));text-align:left}.simple-overview{color:var(--text-secondary);font-size:13px;line-height:1.8}.simple-composer{margin:18px 0 12px}.simple-composer>label{display:block;margin-bottom:8px;font-weight:600}.simple-composer textarea{display:block;box-sizing:border-box;width:100%;min-height:76px;max-width:100%;padding:12px;border:1px solid var(--border);border-radius:10px;resize:vertical;background:var(--background);font:inherit}.simple-primary-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}.simple-primary-actions button{min-height:44px;max-width:100%;white-space:normal}.simple-primary-actions .primary{background:#4c6955;color:white;border-color:#4c6955;min-width:180px}.simple-paper-state{margin:14px 0}.simple-paper-state h3{margin:10px 0}.simple-options{margin-top:18px;border-top:1px solid var(--border);padding-top:12px}.simple-options>summary{cursor:pointer;color:var(--text-secondary)}.simple-workspace select{box-sizing:border-box;max-width:100%;min-width:0}.simple-workspace .home-actions{display:flex;gap:10px;flex-wrap:wrap}.simple-workspace .home-actions>label{min-width:0;max-width:100%}.simple-notice{padding:10px 12px;background:var(--sidebar);border-radius:8px}.simple-workspace p,.simple-workspace li{overflow-wrap:anywhere}.simple-workspace [role=alert]{color:var(--danger,#b13b20)}.simple-workspace :deep(.study-setup-grid){display:block}.simple-workspace :deep(.study-sheet-title),.simple-workspace :deep(.study-suggestion-heading){display:none}.simple-workspace :deep(.markdown-content){max-width:100%;min-width:0}@media(max-width:640px){.simple-primary-actions{display:grid;grid-template-columns:1fr 1fr}.simple-primary-actions .primary{min-width:0}.simple-workspace .home-actions{align-items:stretch;flex-direction:column}}

.simple-recommendation-row{display:block}.simple-recommendations,.simple-frog{min-width:0}.simple-recommendations>h2{font-size:19px;margin:0 0 12px}.simple-frog{position:fixed;inset:96px 20px auto auto;z-index:60;display:flex;flex-direction:column;box-sizing:border-box;width:min(380px,calc(100vw - 40px));height:min(560px,calc(100dvh - 120px));max-height:calc(100dvh - 120px);padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--background);box-shadow:0 12px 36px #0002;overflow:hidden}.simple-frog>header{flex:0 0 auto}.home-chat-close{margin-left:auto;min-height:36px}.simple-frog>[role=alert]{flex:0 0 auto;max-height:80px;overflow-y:auto}.home-chat-launcher{margin-left:auto}.simple-frog .simple-composer{flex:0 0 auto}.simple-frog .simple-composer textarea{resize:none}.simple-frog .simple-composer>label.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.simple-frog>header{display:flex;align-items:center;gap:10px}.simple-frog>header :deep(.study-mascot){width:44px;height:44px}.simple-frog h2{font-size:18px;margin:0}.simple-frog header p{font-size:12px;color:var(--text-secondary);margin:5px 0}.simple-frog .simple-primary-actions{display:flex;justify-content:flex-end;gap:8px}.simple-frog .simple-primary-actions .primary{min-width:0}.simple-frog .simple-composer{margin-top:12px}.simple-frog .simple-options{margin-top:12px}.simple-frog .home-actions>label{width:100%}.simple-frog select{width:100%}.simple-chat-history{max-height:240px;overflow-y:auto;margin-top:12px}.simple-paper-state{border-top:1px solid var(--border);padding-top:14px;margin-top:20px}@media(max-width:960px){.simple-recommendation-row{grid-template-columns:minmax(0,1fr);gap:16px}.simple-frog{padding:14px}}

.recommendation-list-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}.recommendation-list-heading h2{font-size:19px;margin:0}.recommendation-list-heading button{min-height:36px}.manual-scope-editor{padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--background);margin-bottom:14px}.daily-chat-day{font-size:11px;color:var(--text-tertiary);padding:10px 0 6px}.home-daily-chat{display:flex;flex-direction:column;gap:10px;flex:1 1 0;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:12px 8px;background:var(--sidebar);border-radius:10px}.daily-chat-empty{font-size:13px;color:var(--text-secondary);line-height:1.7}.daily-message{max-width:100%;box-sizing:border-box;padding:10px 12px;border-radius:10px;font-size:13px;line-height:1.65;min-width:0}.daily-message b{display:block;font-size:11px;margin-bottom:5px;color:var(--text-secondary)}.daily-message--assistant{align-self:flex-start;background:var(--background);width:94%}.daily-message--user{align-self:flex-end;background:#e7eddf;width:90%}.simple-frog .simple-composer{border-top:1px solid var(--border);padding-top:12px;margin-top:12px}.manual-scope-editor :deep(.study-sheet-title),.manual-scope-editor :deep(.study-suggestion-heading){display:none}.manual-scope-editor :deep(.study-setup-grid){display:block}@media(max-width:640px){.simple-frog{inset:auto 12px 12px; width:calc(100vw - 24px);height:min(560px,calc(100dvh - 24px));max-height:calc(100dvh - 24px)}.home-daily-chat{min-height:0}.home-chat-launcher{margin-left:0}}

.paper-generate-action{display:flex;flex-wrap:wrap;flex-shrink:0;justify-content:flex-start;margin:16px 0 32px;scroll-margin-block:24px}.paper-generate-action .primary{max-width:100%;white-space:normal;scroll-margin-block:24px;background:#4c6955;color:#fff;min-height:44px;min-width:190px}.simple-frog .simple-primary-actions{display:flex;justify-content:flex-end}.simple-frog .simple-primary-actions button{min-width:90px}.simple-frog .daily-message--user{background:#e8f3ff;border:1px solid #cfe3fa}.simple-frog .daily-message--assistant{border:1px solid #e6ebf2;border-radius:14px}.simple-frog .simple-composer textarea{min-height:64px;max-height:128px}@media(max-width:640px){.paper-generate-action .primary{width:100%;min-width:0}}

.manual-recommended{display:grid;gap:8px;border:0;padding:0;margin:12px 0}.manual-recommended legend{font-size:12px;color:var(--text-secondary);margin-bottom:8px}.manual-recommended label{display:flex;align-items:center;gap:8px}.scope-change-summary{padding:10px 12px;background:var(--sidebar);border-radius:8px;font-size:13px}

.manual-scope-editor :deep(.study-config-panel){display:none}
</style>

<style scoped>
.workload-choice{border:1px solid var(--border);border-radius:8px;padding:12px;margin-block:12px;color:var(--text-primary);max-width:100%;overflow-wrap:anywhere}.home-chat-mode{display:flex;gap:12px;font-size:12px;color:var(--text-secondary)}
</style>

<style scoped>
.scope-edit-panel{position:fixed;z-index:80;top:5dvh;left:50%;transform:translateX(-50%);background:var(--background,#fff);box-shadow:0 16px 64px #0003;display:flex;flex-direction:column;box-sizing:border-box;width:min(1120px,calc(100vw - 32px));height:90dvh;min-height:0;min-width:0;max-width:100%;overflow:hidden;border:1px solid var(--border);border-radius:12px;padding:16px;gap:12px}.scope-edit-panel h2{margin:0}.scope-edit-body{flex:1;min-height:0;min-width:0;overflow:hidden;border:0;padding:0;margin:0}.scope-edit-panel footer{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-shrink:0;padding-top:12px;border-top:1px solid var(--border);background:var(--background)}.scope-edit-panel footer span{margin-right:auto}.scope-edit-panel footer button{min-height:42px}@media(max-width:600px){.scope-edit-panel{top:8px;width:calc(100vw - 16px);height:calc(100dvh - 16px);padding:12px}.scope-edit-panel footer{gap:8px;flex-wrap:wrap}}
</style>

<style scoped>
@media(min-width:961px){.chat-open .recommendation-list-heading{padding-right:450px;min-height:48px}}
@media(max-width:640px){.simple-frog{position:relative;inset:auto;transform:none;width:100%;height:min(480px,65dvh);max-height:65dvh;margin-block:12px;box-sizing:border-box}}
</style>
