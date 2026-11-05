<script setup lang="ts">
// 专注模式：提交后保留当前题供查看解析，由用户主动继续。
// 查看答案记录首次查看时间，但不改变掌握度与毕业；旧 GET 接口仍只读。

import { roleLabel, typeLabel } from "../lib/labels";
import { answerFeedback, answerAssessmentNote } from "../lib/answerFeedback";
import { answerInputHint } from "../lib/answerInput";
import { allowsSelfReport, answerSubmissionLabel, answerGradingNotice } from "../lib/answerInteraction";
import SelfReportActions from "./SelfReportActions.vue";
import QuestionSource from "./QuestionSource.vue";
import MarkdownContent from "./MarkdownContent.vue";
import AnswerExplanation from './AnswerExplanation.vue';
import type { PlanItemView, PracticeItemAnswer, SelfGrade } from "../types/practice";

const props = defineProps<{
  item: PlanItemView | null;
  answer?: PracticeItemAnswer;
  answerOpen: boolean;
  answerLoading: boolean;
  answerError: string | null;
  submitting: boolean;
  retryLoading?: boolean;
  standalone?: boolean;
  readOnly?: boolean;
  allowSkip?: boolean;
  showAnswerReveal?: boolean;
  allowSelfReport?: boolean;
  emptyTitle?: string;
  emptyMessage?: string;
  showGradingNotice?: boolean;
  notice?: string;
  gradeError?: string;
  submissionNeedsRefresh?: boolean;
  hasPrevious: boolean;
  hasNext: boolean;
  displayNumber: number;
  rawAnswer: string;
  selectedOption?: string;
}>();

const emit = defineEmits<{
  reveal: [];
  grade: [grade: SelfGrade];
  "submit-answer": [];
  "refresh-submission": [];
  retry: [];
  continue: [];
  previous: [];
  skip: [];
  "update:rawAnswer": [value: string];
  "update:selectedOption": [value: string];
}>();

</script>

<template>
  <div v-if="!props.item" class="state state--empty" data-testid="focus-empty">
    <p>{{ props.emptyTitle ?? "当前没有待作答题目" }}</p>
    <p>{{ props.emptyMessage ?? "可以在「阅览全卷」里回看；有错题时也可使用重练或追加练习。" }}</p>
  </div>

  <article v-else class="focus-card" data-testid="focus-question" :data-item-id="props.item.id"
    :data-question-version-id="props.item.question_version_id ?? ''" :data-display-number="props.displayNumber" tabindex="-1">
    <header>
      <strong v-if="props.standalone">错题重练（不计入今日卷题号）</strong>
      <strong v-else>第 {{ props.displayNumber }} 题</strong>
      <span class="focus-meta">{{ typeLabel(props.item.question_type) }}</span>
      <span v-if="props.item.answer_submission" class="focus-remaining" :data-result="answerFeedback(props.item.answer_submission).tone">已提交</span>
      <span v-else class="focus-remaining">{{ props.item.completed ? "已完成" : "未完成" }}</span>
    </header>
    <div class="focus-controls">
      <nav class="question-navigation question-navigation--top" aria-label="切换题目">
        <button type="button" :disabled="!props.hasPrevious || props.submitting || props.answerLoading" data-testid="previous-question" @click="emit('previous')">上一题</button>
        <button type="button" :disabled="!props.hasNext || props.submitting || props.answerLoading" data-testid="continue-question" @click="emit('continue')">下一题</button>
        <button v-if="props.allowSkip && !props.readOnly && !props.item.completed && !props.item.answer_submission" type="button" :disabled="props.submitting || props.answerLoading" data-testid="skip-question" @click="emit('skip')">稍后再做</button>
      </nav>
      <button v-if="props.showAnswerReveal !== false && !props.item.is_external_reference" class="answer-explanation-toggle" type="button" data-testid="answer-explanation" :disabled="props.answerLoading" :aria-expanded="props.answerOpen" :aria-controls="`focus-answer-${props.item.id}`" @click="emit('reveal')">
        {{ props.answerLoading ? "加载中…" : props.answerOpen ? "收起答案详解" : "查看答案详解" }}
      </button>
    </div>
    <button v-if="props.item.answer_submission?.result === 'wrong' && !props.standalone && !props.item.retry_source_id" type="button" data-testid="retry-practice" :disabled="props.submitting || props.retryLoading" @click="emit('retry')">{{ props.retryLoading ? '正在读取重练状态…' : '再练一次（保留原记录）' }}</button>
    <p v-if="props.item.answer_submission?.result === 'wrong' && (props.standalone || props.item.retry_source_id)" data-testid="retry-limit-notice">本次重练错误已保留，不再创建下一层重练。请回看本题解析，再通过上方“返回今日卷”或“追加练习题”复习其他内容。</p>
    <p v-if="props.standalone && props.item.answer_revealed_at" data-testid="retry-assisted-notice">本题已查看解析或继承辅助事实；本次重练答对不记为独立掌握。</p>
    <div class="focus-workspace" :class="{ 'focus-workspace--single': props.showAnswerReveal === false }">
      <div class="focus-question-main">
    <QuestionSource :source="props.item.question_source" :trust="props.item.question_trust" :show-original-number="false" :is-variant="props.item.is_variant" />
    <p v-if="props.item.question_trust?.teaching_use === 'REFERENCE_ONLY'" class="answer-provenance" data-testid="teaching-reference-notice">参考学习题 · 暂不支持可靠自动判题</p>
    <p v-if="props.item.question_trust?.answer_provenance === 'ai_generated'" class="answer-provenance" data-testid="ai-answer-provenance">
      {{ props.item.question_trust.content_trust === 'source_attested' && props.item.question_trust.answer_reliability === 'ai_generated_consistent'
        ? '来源与题面结构已机器校验 · AI答案经三角色交叉核对一致 · 题解未单独核验'
        : props.item.question_trust.answer_reliability === 'ai_disagreement'
        ? 'AI 答案存在独立求解分歧 · 已停用自动判题，仅供复习参考'
        : props.item.question_trust.answer_reliability === 'ai_generated_consistent'
          ? 'AI 生成参考答案 · 多次独立求解一致，仍非官方答案'
          : 'AI 生成参考答案 · 暂无已核验参考答案' }}
    </p>
    <details class="question-meta">
      <summary>题目信息</summary>
      <div>{{ props.item.kp_name }} · {{ roleLabel(props.item.question_role) }} · 预计 {{ props.item.estimated_minutes }} 分钟</div>
      <div v-if="props.item.is_variant || props.item.is_review">{{ props.item.is_variant ? "变式题" : "" }}{{ props.item.is_variant && props.item.is_review ? " · " : "" }}{{ props.item.is_review ? "复测" : "" }}</div>
      <div v-if="props.item.skill_tags.length">考法：{{ props.item.skill_tags.join("、") }}</div>
      <div v-if="props.item.answer_submission && answerAssessmentNote(props.item.answer_submission)" data-testid="answer-assessment-note">{{ answerAssessmentNote(props.item.answer_submission) }}</div>
    </details>

    <MarkdownContent class="stem" data-testid="focus-stem" :text="props.item.stem ?? ''" />

    <ul v-if="props.item.options" class="options">
      <li v-for="(text, key) in props.item.options" :key="key">
        <label class="option-choice">
          <input
            type="radio"
            :name="`option-${props.item.id}`"
            :value="key"
            :checked="props.selectedOption === key"
            :disabled="props.item.completed || props.submitting || props.readOnly"
            :data-testid="`option-${key}`"
            @change="emit('update:selectedOption', key)"
          />
          <MarkdownContent class="option-content" :text="`${key}. ${text}`" />
        </label>
      </li>
    </ul>

    <label v-if="!props.item.options" class="raw-answer">
      <span>记录最终答案或关键结论</span>
      <textarea
        :value="props.rawAnswer"
        rows="2"
        :disabled="props.item.completed || props.submitting || props.readOnly"
        :placeholder="answerInputHint(props.item.answer_grading_method, props.item.question_type)"
        data-testid="raw-answer"
        @input="emit('update:rawAnswer', ($event.target as HTMLTextAreaElement).value)"
      ></textarea>
    </label>

    <button v-if="!props.item.completed && !props.readOnly" type="button" :disabled="props.submitting || props.answerLoading || Boolean(props.submissionNeedsRefresh) || (props.item.question_type === 'single_choice' && (!props.selectedOption || !Object.prototype.hasOwnProperty.call(props.item.options ?? {}, props.selectedOption)))" data-testid="submit-answer" @click="emit('submit-answer')">{{ props.submitting ? "提交中…" : answerSubmissionLabel(props.item) }}</button>
    <div v-if="props.item.answer_submission" class="answer-result" :data-result="answerFeedback(props.item.answer_submission).tone" role="status">
      <strong><span data-testid="answer-submission-notice" :data-result="answerFeedback(props.item.answer_submission).tone" :aria-label="answerFeedback(props.item.answer_submission).label">{{ answerFeedback(props.item.answer_submission).symbol }}</span> <span data-testid="answer-result-label">{{ answerFeedback(props.item.answer_submission).label }}</span></strong>
      <span>本次答案已提交并锁定，可以继续查看解析。</span>
      <small v-if="answerAssessmentNote(props.item.answer_submission)">{{ answerAssessmentNote(props.item.answer_submission) }}</small>
    </div>
    <p v-else-if="!props.item.completed" class="answer-hint">{{ props.item.question_type === 'single_choice' ? '请选择一个选项后提交；未选择时不会保存本次作答。' : '提交后本次答案锁定；未填写时会记录为未作答。' }}</p>
    <p v-if="props.showGradingNotice !== false" class="answer-hint" data-testid="answer-grading-boundary">{{ answerGradingNotice(props.item) }}</p>
    <SelfReportActions v-if="props.allowSelfReport !== false && !props.item.completed && allowsSelfReport(props.item)" :disabled="props.submitting" test-prefix="self-grade" @grade="emit('grade', $event)" />

    <p v-if="props.notice" class="notice" data-testid="focus-notice">{{ props.notice }}</p>
    <p v-if="props.gradeError" class="form-error">{{ props.gradeError }}</p>
    <button v-if="props.submissionNeedsRefresh" type="button" :disabled="props.submitting" data-testid="refresh-answer-state" @click="emit('refresh-submission')">刷新学习状态</button>
    <slot name="process-review" />
      </div>
      <aside v-if="props.showAnswerReveal !== false" class="focus-answer-pane" aria-label="答案详解">
        <p v-if="props.answerError" class="form-error">{{ props.answerError }}</p>
        <div v-if="props.answerOpen && props.answer" :id="`focus-answer-${props.item.id}`" class="answer-box" data-testid="focus-answer">
          <p class="answer-provenance" data-testid="answer-provenance-notice">{{ props.answer.answer_notice }}</p>
          <strong>参考答案：</strong><MarkdownContent :text="props.answer.correct_answer ?? '（无标准答案，请自行对照解析）'" />
          <strong>参考解析：</strong><AnswerExplanation :text="props.answer.explanation" />
        </div>
      </aside>
    </div>
  </article>
</template>

<style scoped>
.answer-result{display:grid;gap:5px;margin:14px 0;padding:12px 15px;border:1px solid #d6dfcf;border-radius:12px;background:#f0f5eb;color:#425a3b}
.answer-result[data-result="wrong"]{background:#fff3ef;border-color:#e9cec3;color:#984c38}
.answer-result[data-result="unknown"]{background:#f6f4eb;border-color:#ded8bd;color:#75633d}
.answer-result span,.answer-result small{font-size:12px;line-height:1.6}
.focus-card { max-width: none; margin: 0; padding: 26px 18px 42px; border: 0; border-radius: 0; }
.focus-workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .9fr); align-items: start; gap: 32px; }
.focus-workspace--single { grid-template-columns: minmax(0, 1fr); }
.focus-question-main, .focus-answer-pane { min-width: 0; }
.focus-controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.focus-controls .question-navigation { margin: 0; }
.answer-explanation-toggle { flex: 0 0 auto; }
.focus-answer-pane { padding: 4px 0 0 22px; border-left: 1px solid var(--border); }
.focus-card header { gap: 10px; padding-bottom: 20px; color: var(--text-tertiary); font-size: 12px; }
.focus-card header strong { color: var(--text); font-size: 13px; }
.focus-meta { color: var(--text-tertiary); }
.focus-remaining { margin-left: auto; color: var(--text-tertiary); }
.focus-remaining[data-result="wrong"] { color: #a64b4b; font-size: 22px; line-height: 1; }
.focus-remaining[data-result="right"] { color: #42755a; font-size: 18px; line-height: 1; }
.question-meta { margin: -12px 0 20px; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }
.question-meta summary { width: fit-content; cursor: pointer; }
.question-meta > div { margin: 4px 0 0 12px; }
.focus-card .stem { margin: 0 0 24px; color: var(--text); font-size: clamp(19px, 2vw, 23px); font-weight: 500; line-height: 1.8; white-space: pre-wrap; }
.focus-card .options { display: grid; gap: 7px; margin: 0 0 22px; }
.option-content :deep(p) { margin: 0; }
.focus-card .option-choice { align-items: center; gap: 12px; min-height: 46px; padding: 9px 12px; border: 1px solid transparent; border-radius: 6px; font-size: 15px; line-height: 1.55; }
.focus-card .option-choice:hover { background: #f7f7f7; }
.focus-card .option-choice:has(input:checked) { border-color: #d9dadd; background: #f5f5f5; }
.focus-card .raw-answer { margin: 0 0 18px; }
.focus-card .raw-answer textarea { min-height: 72px; padding: 12px; font-size: 15px; line-height: 1.6; resize: vertical; }
.focus-card .answer-box { margin-top: 18px; padding: 0; border: 0; background: transparent; overflow-wrap: anywhere; }
.focus-card .answer-provenance { margin: 4px 0 10px; color: var(--text-tertiary); font-size: 12px; }
  .grade-prompt { margin: 28px 0 3px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--text-tertiary); font-size: 12px; }
  .answer-hint { color: var(--text-tertiary); font-size: 12px; }
.focus-card .actions--grades { margin-top: 6px; }
.focus-card .actions--grades button { border-color: transparent; color: var(--text-secondary); background: #f5f5f5; font-weight: 400; }
.focus-card .actions--grades button:hover:not(:disabled) { color: var(--text); background: #ebebeb; }
.focus-card .notice { margin-top: 14px; border: 0; background: transparent; color: var(--text-secondary); font-size: 12px; }
.question-navigation { display: flex; gap: 12px; margin-top: 24px; }
.question-navigation--top { margin: 0 0 12px; }
.question-navigation button { background: transparent; color: var(--text-secondary); border-color: transparent; font-weight: 400; }
@media (max-width: 600px) {
  .focus-card { padding: 16px 0 32px; }
  .focus-card header { gap: 7px; }
  .focus-controls { align-items: flex-start; flex-wrap: wrap; }
  .answer-explanation-toggle { order: -1; }
}
@container (max-width: 780px) {
  .focus-workspace { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  .focus-answer-pane { padding: 18px 0 0; border-top: 1px solid var(--border); border-left: 0; }
}
</style>
