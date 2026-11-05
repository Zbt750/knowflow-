const labels:Record<string,string>={exam_curated:'真题改编（整理）',exam_variant:'真题改编（变式）',development_original:'开发原创',
 personal_ai_practice:'个人 AI 练习',personal_practice:'个人练习',unclassified_public:'其他来源（待核）'};
export function questionSourceLabel(value:string):string{return labels[value]??`其他真实来源（${value}）`;}
