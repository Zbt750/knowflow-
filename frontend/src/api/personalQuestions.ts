import { api } from './client';
import type {TodayAppendResult} from './todayAppend';
export type GenerationConfirmation = {
  difficulty_steps?: string[];
  proposed_targets?: Array<{kp_id:string;name:string;question_type:string;count:number;difficulty:string}> | null;
  reference_text?: string;
  question: string; message: string; selected_kp_id: string | null; question_count: number; difficulty: string;
  nodes: Array<{ kp_id: string; name: string; code: string; question_types: string[] }>;
};
export type DifficultySummary = {
  target_label:string;estimated_label:string;relative_label:string;relative_estimate:string;notice:string;
  target_basis?:'explicit'|'relative_inferred'|'request_default';
  requirement:{raw_text:string;target_level:string;relative_change:string;absolute_explicit:boolean};
  model_assessment?:{estimated_level:string;relative_change:string;reason:string;mechanisms:string[]}|null;
  independent_check:{status:string;issues:string[];reference_available:boolean};
  constraint_check?:{status:string;issues:string[]};
};
export type PersonalQuestion = { id:string;kp_id:string;bank_scope:'public'|'personal';hidden:boolean;
  difficulty_summary?:DifficultySummary|null;
  question_type:string;difficulty:string;stem:string;options:Record<string,string>|null;practice_eligible:boolean };
export type GenerationResult = {batch_id:string;status:string;question_ids:string[];message:string;
  append_results?:TodayAppendResult[];
  outcome_summary?:{requested_count:number;saved_count:number;failed_count:number;attempted_count:number|null;
    not_attempted_count:number|null;not_executed_count?:number|null;network_failed_count?:number;
    unresolved_count:number;provider_calls:number;quality_rejected_count:number;
    response_failed_count:number;structure_rejected_count:number;failure_details:Array<{code:string;count:number;message:string}>};
  difficulty_summaries?:Record<string,DifficultySummary>;
  diagnostics?:Array<{index?:number;code:string;stage:string;message:string;network_cause?:string;failure_reason?:string}>;
  reference_only_question_ids?:string[];
  plan_id?:string;appended_question_ids?:string[];numbers?:Array<{question_id:string;item_id:string;number:number;question_type:string}>;append_error?:string};
export const readBank=(scope:'public'|'personal',kpId?:string,search='',offset=0,includeHidden=false,limit=20)=>api.get<{total:number;items:PersonalQuestion[]}>(
  `/api/question-bank?scope=${scope}&include_hidden=${includeHidden}&limit=${Math.min(100,Math.max(1,limit))}&offset=${offset}&search=${encodeURIComponent(search)}${kpId?`&kp_id=${encodeURIComponent(kpId)}`:''}`);
export const hidePersonal=(id:string,hidden:boolean)=>api.patch(`/api/personal-questions/${id}/visibility`,{hidden});
export const appendPersonal=(ids:string[],planId?:string)=>api.post<{plan_id:string;numbers:GenerationResult['numbers'];added:number;append_result?:TodayAppendResult|null}>(
  '/api/personal-questions/append',{question_ids:ids,plan_id:planId});
export const readGeneration=(key:string)=>api.get<GenerationResult>(`/api/personal-questions/batches/${key}`);

export type ImageVariantRequest = {
  request_key: string;
  generation_mode: 'ai_enhanced' | 'ai_generated';
  targets: Array<{ kp_id: string; question_type: string; count: number; difficulty: string }>;
  reference_text?: string;
  reference_source?: Record<string, unknown>;
  user_requirement?: string;
};

/** 图片识别文本 → 个人变式练习；模式由调用方显式选择，不静默切换。 */
export const generatePersonalQuestions=(body:ImageVariantRequest)=>api.post<GenerationResult>(
  '/api/personal-questions/generate',{surface:'chat',...body});
