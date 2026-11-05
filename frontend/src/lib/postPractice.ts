import type {components} from '../api/types';
export type PostPractice=components['schemas']['PostGraduationPractice'];
export function postPracticeSummary(p:PostPractice|null|undefined){
  if(!p?.applicable)return null;
  return {foundation:'基础毕业：已通过',label:p.label,reason:p.reason,review:p.status==='CONSOLIDATE'||p.status==='REVIEW'};
}
