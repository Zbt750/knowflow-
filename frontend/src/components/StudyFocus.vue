<script setup lang="ts">
// 专注模式：提交后保留当前题供查看解析，由用户主动继续。
// 查看答案记录首次查看时间，但不改变掌握度与毕业；旧 GET 接口仍只读。

import { roleLabel, typeLabel } from "../lib/labels";
import { answerFeedback } from "../lib/answerFeedback";
import { answerInputHint } from "../lib/answerInput";
import { canRetryAnswer } from "../lib/attemptSequence";
import SelfReportActions from "./SelfReportActions.vue";
import type { PlanItemView, PracticeItemAnswer, SelfGrade } from "../types/practice";

const props = defineProps<{
  item: PlanItemView | null;
  answer?: PracticeItemAnswer;
  answerOpen: boolean;
  answerLoading: boolean;
  answerError: string | null;
  submitting: boolean;
  notice?: string;
  gradeError?: string;
  remaining: number;
  displayNumber: number;
  rawAnswer: string;
  confidence: string;
  selectedOption?: string;
  retrying?: boolean;
}>();

const emit = defineEmits<{
  reveal: [];
  grade: [grade: SelfGrade];
  "submit-answer": [];
  continue: [];
  retry: [];
  "cancel-retry": [];
  "update:rawAnswer": [value: string];
  "update:confidence": [value: string];
  "update:selectedOption": [value: string];
}>();

</script>

<template>
  <div v-if="!props.item" class="state state--empty" data-testid="focus-empty">
    <p>今天的题都做完了，可以在「阅览全卷」里回看。</p>
    <p>想继续练就点下面的「追加练习题」：选中的题会加到卷尾，今天的计划会重新变成进行中。</p>
  </div>

  <article v-else class="focus-card" data-testid="focus-question" tabindex="-1">
    <header>
      <strong>第 {{ props.displayNumber }} 题</strong>
      <span class="focus-meta">{{ typeLabel(props.item.question_type) }}</span>
      <span v-if="props.item.answer_submission" class="focus-remaining" role="status" :aria-label="answerFeedback(props.item.answer_submission).label" :data-result="answerFeedback(props.item.answer_submission).tone" data-testid="answer-submission-notice">{{ answerFeedback(props.item.answer_submission).symbol }}</span>
      <span v-else class="focus-remaining">{{ props.item.completed ? "已完成" : "未完成" }}</span>
    </header>
    <div class="focus-workspace">
      <div class="focus-question-main">
    <details class="question-meta">
      <summary>题目信息</summary>
      <div>{{ props.item.kp_name }} · {{ roleLabel(props.item.question_role) }} · 预计 {{ props.item.estimated_minutes }} 分钟</div>
      <div v-if="props.item.is_variant || props.item.is_review">{{ props.item.is_variant ? "变式题" : "" }}{{ props.item.is_variant && props.item.is_review ? " · " : "" }}{{ props.item.is_review ? "复测" : "" }}</div>
      <div v-if="props.item.skill_tags.length">考法：{{ props.item.skill_tags.join("、") }}</div>
    </details>

    <p class="stem" data-testid="focus-stem">{{ props.item.stem }}</p>

    <ul v-if="props.item.options" class="options">
      <li v-for="(text, key) in props.item.options" :key="key">
        <label class="option-choice">
          <input
            type="radio"
            :name="`option-${props.item.id}`"
            :value="key"
            :checked="props.selectedOption === key"
            :disabled="(props.item.completed && !props.retrying) || props.submitting"
            :data-testid="`option-${key}`"
            @change="emit('update:selectedOption', key)"
          />
          <span>{{ key }}. {{ text }}</span>
        </label>
      </li>
    </ul>

    <label v-if="!props.item.options" class="raw-answer">
      <span>纸上作答，记录最终答案或关键结论（可选）</span>
      <textarea
        :value="props.rawAnswer"
        rows="2"
        :disabled="(props.item.completed && !props.retrying) || props.submitting"
        :placeholder="answerInputHint(props.item.answer_grading_method)"
        data-testid="raw-answer"
        @input="emit('update:rawAnswer', ($event.target as HTMLTextAreaElement).value)"
      ></textarea>
    </label>

    <label class="answer-hint">做题信心（可选）
      <select :value="props.confidence" :disabled="(props.item.completed && !props.retrying) || props.submitting" data-testid="answer-confidence" @change="emit('update:confidence', ($event.target as HTMLSelectElement).value)">
        <option value="">未填写</option><option value="certain">很确定</option><option value="uncertain">有思路但不稳</option><option value="guess">猜的</option><option value="no_idea">完全不会</option>
      </select>
    </label>
    <button v-if="!props.item.completed || props.retrying" type="button" :disabled="props.submitting || props.answerLoading" data-testid="submit-answer" @click="emit('submit-answer')">{{ props.submitting ? "提交中…" : props.item.answer_grading_method ? "提交答案" : "记录作答" }}</button>
    <button v-else type="button" :disabled="props.submitting || props.answerLoading" data-testid="continue-question" @click="emit('continue')">{{ props.remaining ? "下一题" : "完成回看" }}</button>
    <button v-if="props.item.completed && !props.retrying && canRetryAnswer(props.item.answer_submission)" type="button" :disabled="props.submitting || props.answerLoading" data-testid="retry-answer" @click="emit('retry')">再试一次</button>
    <button v-if="props.retrying" type="button" :disabled="props.submitting" data-testid="cancel-answer-retry" @click="emit('cancel-retry')">取消修改</button>
    <p class="answer-hint">{{ props.item.answer_grading_method ? "只核对最终答案，不评价推导过程。" : "本题暂不自动判分，提交仅保存作答记录。" }}</p>
    <button v-if="!props.item.completed" type="button" :disabled="props.submitting" data-testid="self-grade-skip" @click="emit('grade', 'skip')">跳过</button>
    <SelfReportActions v-if="!props.item.completed && !props.item.answer_grading_method" :disabled="props.submitting" test-prefix="self-grade" @grade="emit('grade', $event)" />

    <p v-if="props.notice" class="notice" data-testid="focus-notice">{{ props.notice }}</p>
    <p v-if="props.gradeError" class="form-error">{{ props.gradeError }}</p>
    <slot name="process-review" />
      </div>
      <aside class="focus-answer-pane" aria-label="答案详解">
        <button type="button" data-testid="answer-explanation" :disabled="props.answerLoading" :aria-expanded="props.answerOpen" :aria-controls="`focus-answer-${props.item.id}`" @click="emit('reveal')">
          {{ props.answerLoading ? "加载中…" : props.answerOpen ? "收起答案详解" : "查看答案详解" }}
        </button>
        <p v-if="props.answerError" class="form-error">{{ props.answerError }}</p>
        <div v-if="props.answerOpen && props.answer" :id="`focus-answer-${props.item.id}`" class="answer-box" data-testid="focus-answer">
          <p><strong>参考答案：</strong>{{ props.answer.correct_answer ?? "（无标准答案，请自行对照解析）" }}</p>
          <p><strong>解析：</strong>{{ props.answer.explanation }}</p>
        </div>
      </aside>
    </div>
  </article>
</template>

<style scoped>
.focus-card { max-width: none; margin: 0; padding: 26px 18px 42px; border: 0; border-radius: 0; }
.focus-workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .9fr); align-items: start; gap: 32px; }
.focus-question-main, .focus-answer-pane { min-width: 0; }
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
.focus-card .option-choice { align-items: center; gap: 12px; min-height: 46px; padding: 9px 12px; border: 1px solid transparent; border-radius: 6px; font-size: 15px; line-height: 1.55; }
.focus-card .option-choice:hover { background: #f7f7f7; }
.focus-card .option-choice:has(input:checked) { border-color: #d9dadd; background: #f5f5f5; }
.focus-card .raw-answer { margin: 0 0 18px; }
.focus-card .raw-answer textarea { min-height: 72px; padding: 12px; font-size: 15px; line-height: 1.6; resize: vertical; }
.focus-card .answer-box { margin-top: 18px; padding: 0; border: 0; background: transparent; overflow-wrap: anywhere; }
  .grade-prompt { margin: 28px 0 3px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--text-tertiary); font-size: 12px; }
  .answer-hint { color: var(--text-tertiary); font-size: 12px; }
.focus-card .actions--grades { margin-top: 6px; }
.focus-card .actions--grades button { border-color: transparent; color: var(--text-secondary); background: #f5f5f5; font-weight: 400; }
.focus-card .actions--grades button:hover:not(:disabled) { color: var(--text); background: #ebebeb; }
.focus-card .notice { margin-top: 14px; border: 0; background: transparent; color: var(--text-secondary); font-size: 12px; }
@media (max-width: 600px) { .focus-card { padding: 16px 0 32px; } .focus-card header { gap: 7px; } }
@container (max-width: 780px) {
  .focus-workspace { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  .focus-answer-pane { padding: 18px 0 0; border-top: 1px solid var(--border); border-left: 0; }
}
</style>
