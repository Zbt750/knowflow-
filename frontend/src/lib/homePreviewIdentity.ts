import type {HomePreview,HomePaper} from '../api/homeRecommendation';

export function homePreviewIdentity(p:HomePreview|null):string {
 return p ? `${p.session_id}/${p.task_id}/${p.draft_version??p.status}` : '';
}

export function coherentHomePreview(p:HomePreview|null):boolean {
 if(!p?.draft||!p.draft_version||!p.context||p.status!=='ready')return false;
 return coherentHomePaper(p.draft,p.budget_minutes,p.context.workload);
}

export function coherentHomePaper(d:HomePaper,budget:number,workload?:HomePreview['context']['workload']):boolean {
 if(d.question_count!==undefined){
  const count=d.question_count,nodes=d.scope_nodes??[];
  return Number.isInteger(count)&&count>0&&Number.isFinite(d.total_minutes)&&d.total_minutes>0
   &&d.budget_minutes===budget&&Array.isArray(d.questions)&&d.questions.length===0
   &&new Set(nodes.map(n=>n.kp_id)).size===nodes.length
   &&nodes.every(n=>Number.isInteger(n.assigned_count)&&n.assigned_count>=0)
   &&nodes.reduce((sum,n)=>sum+n.assigned_count,0)===count
   &&(d.total_minutes<=budget||!!workload?.requires_confirmation);
 }
 if(!Array.isArray(d.questions)||!Number.isFinite(d.total_minutes))return false;
 const ids=d.questions.map(q=>q?.question_id);
 return d.budget_minutes===budget && d.questions.length>0
  && new Set(ids).size===ids.length
  && d.questions.every(q=>q?.question_id&&q.question_version_id&&Number.isFinite(q.minutes)&&q.minutes>0)
  && d.total_minutes===d.questions.reduce((sum,q)=>sum+q.minutes,0)
  && (d.total_minutes<=budget || (workload?.requires_confirmation===true
    && workload.requested_budget_minutes===budget
    && workload.effective_budget_minutes===d.total_minutes
    && workload.extra_minutes===d.total_minutes-budget));
}
