import {ApiError} from '../api/client';

export function answerSubmissionFailure(error: unknown): {message: string; requiresRefresh: boolean; reload: boolean} {
  if (!(error instanceof ApiError) || error.status === null || error.status >= 500) {
    return {message:'提交结果暂未确认，请先刷新查看作答记录；若尚未保存，再提交相同答案。', requiresRefresh:true, reload:false};
  }
  const code=error.code ?? 'unknown';
  if (code === 'validation_failed') return {message:error.message,requiresRefresh:false,reload:false};
  const messages:Record<string,string>={
    kp_state_not_found:'学习状态暂不可用，本次提交未保存。请先刷新学习状态；若仍失败，请保留错误码联系维护者。',
    graduation_set_binding_missing_for_started_learner:'该知识点的正式题集绑定需要核对，本次提交未保存。请先刷新并检查学习范围。',
    practice_item_already_assessed:'本题已提交，请查看已保存的作答记录。',
    answer_attempt_conflict:'作答记录已变化，请查看刷新后的记录。',
    answer_question_changed:'题目版本已变化，本次提交未保存，请重新安排这道题。',
    idempotency_key_conflict:'这次提交标识与已保存记录冲突，请先刷新核对，勿重复提交。',
  };
  const reload=['practice_item_already_assessed','answer_attempt_conflict','answer_question_changed'].includes(code);
  const message=messages[code] ?? (error.status===401 || error.status===403
    ? '当前会话没有提交权限，请检查会话状态；请勿重复点击提交。'
    : '本次提交被服务端拒绝，请先刷新核对题目和作答记录。');
  return {message:`${message}（${code}）`,requiresRefresh:!reload,reload};
}
