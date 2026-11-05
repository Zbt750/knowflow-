import type {HomePaper} from '../api/homeRecommendation';
export const homePaperCount=(p:HomePaper|null|undefined)=>p?.question_count??p?.questions.length??0;
export const homeNodeCount=(p:HomePaper|null|undefined,id:string)=>p?.scope_nodes?.find(n=>n.kp_id===id)?.assigned_count??p?.questions.filter(q=>q.kp_id===id).length??0;
