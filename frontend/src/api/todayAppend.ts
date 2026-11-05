export type TodayAppendItem={item_id:string;question_id:string;question_version_id:string;number:number;stem:string;
  options:Record<string,string>|null;kp_id:string;kp_name:string;question_type:string;difficulty:string|null;
  source_category:string;question_source:Record<string,unknown>;estimated_minutes:number|null};
export type TodayAppendResult={operation_id:string;plan_id:string;study_date:string;status:'committed';
  number_semantics:'current_position';added_count:number;total_count:number;items:TodayAppendItem[]};
