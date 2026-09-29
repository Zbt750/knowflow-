// 统一的异步任务状态：loading / success / error / submitting。
// 页面不再各自发明状态名，避免同一个动作在不同页面表现不一致。
//
// 这个 composable 是阶段 E「统一状态」的落点：四个页面（/study /knowledge
// /materials /chat）的加载、提交、失败都从它取状态与错误码，
// 而不是各写一套 `const state = ref("loading")` + 各自的 catch 分支。
//
// 两个选项是为真实页面行为准备的，不是抽象洁癖：
// - `keepPreviousData`：刷新时不要在已有数据的情况下闪回 loading 空态。
//   学习页实测踩过：自评后刷新会把 `study-active` 整块从 DOM 摘掉再装回来，
//   用户点「全卷模式」会看到卷子消失，自动化里表现为 paper-list 时有时无。
// - `errorMessages`：有些错误码要给出比后端文案更可操作的指引
//   （例如 kp_state_not_found → 提示先跑 seed.py）。映射留在页面侧声明，
//   文字不进 composable，避免这里变成业务文案仓库。

import { ref, type Ref } from "vue";

import { ApiError } from "../api/client";

export type LoadState = "idle" | "loading" | "success" | "error";

/**
 * 页面主动放弃一次请求结果时抛它（典型场景：请求令牌发现响应过期）。
 *
 * 为什么不直接抛普通 Error：那样会被当成失败写进 error 态，
 * 页面会显示一条根本不存在的错误。实测场景：学习页连点自评会并发触发刷新，
 * 晚发出的请求可能先返回，早返回的那次结果必须**静默丢弃** ——
 * 既不改数据，也不改状态。
 */
export class StaleResponse extends Error {
  constructor() {
    super("stale response discarded");
    this.name = "StaleResponse";
  }
}

export interface RunOptions {
  /** 已有数据时刷新不切回 loading，保持当前视图，刷新在后台完成。 */
  keepPreviousData?: boolean;
}

export interface AsyncTaskOptions {
  /** 按错误码覆盖展示文案；未命中时用后端 message。 */
  errorMessages?: Record<string, string>;
  /** 非 ApiError 时的兜底文案（网络中断等没有错误码的情况）。 */
  fallbackMessage?: string;
}

export interface AsyncTask<T> {
  data: Ref<T | null>;
  state: Ref<LoadState>;
  errorCode: Ref<string | null>;
  errorMessage: Ref<string | null>;
  submitting: Ref<boolean>;
  run: (loader: () => Promise<T>, options?: RunOptions) => Promise<T | null>;
  submit: (action: () => Promise<T>) => Promise<T | null>;
  reset: () => void;
}

export function useAsyncTask<T>(
  initial: T | null = null,
  options: AsyncTaskOptions = {},
): AsyncTask<T> {
  const data = ref<T | null>(initial) as Ref<T | null>;
  // 初始就是 loading：页面挂载后马上会发起首次加载，用 idle 会让首个渲染帧
  // 既没有加载态也没有内容（实测：知识页会短暂什么都不显示）。
  const state = ref<LoadState>("loading");
  const errorCode = ref<string | null>(null);
  const errorMessage = ref<string | null>(null);
  const submitting = ref(false);
  let generation = 0;
  let submitGeneration = 0;

  function cancelled(error: unknown): boolean {
    return error instanceof StaleResponse || (error instanceof Error && error.name === "AbortError");
  }

  function applyError(error: unknown): void {
    state.value = "error";
    if (error instanceof ApiError) {
      errorCode.value = error.code;
      const mapped = error.code ? options.errorMessages?.[error.code] : undefined;
      errorMessage.value = mapped ?? error.message;
    } else {
      errorCode.value = null;
      errorMessage.value = options.fallbackMessage ?? "请求失败";
    }
  }

  async function run(loader: () => Promise<T>, runOptions: RunOptions = {}): Promise<T | null> {
    const token = ++generation;
    // 关键：是否切 loading 取决于「现在有没有可展示的数据」，
    // 而不是无脑切换。这样页面不会在后台刷新时闪一下空态。
    const keepData = runOptions.keepPreviousData === true && data.value !== null;
    if (!keepData) state.value = "loading";
    errorCode.value = null;
    errorMessage.value = null;
    try {
      const result = await loader();
      if (token !== generation) return null;
      data.value = result;
      state.value = "success";
      return result;
    } catch (error) {
      if (token !== generation) return null;
      if (cancelled(error)) {
        // 页面主动丢弃这次结果（响应过期）：状态与数据都维持原样。
        if (state.value === "loading") state.value = data.value === null ? "idle" : "success";
        return data.value;
      }
      applyError(error);
      return null;
    }
  }

  async function submit(action: () => Promise<T>): Promise<T | null> {
    if (submitting.value) return null;
    const token = ++generation;
    const submitToken = ++submitGeneration;
    // 提交期间禁用按钮，防止用户重复点击造成重复历史。
    submitting.value = true;
    errorCode.value = null;
    errorMessage.value = null;
    try {
      const result = await action();
      if (token !== generation) return null;
      data.value = result;
      state.value = "success";
      return result;
    } catch (error) {
      if (token !== generation || cancelled(error)) return null;
      applyError(error);
      return null;
    } finally {
      if (submitToken === submitGeneration) submitting.value = false;
    }
  }

  function reset(): void {
    generation += 1;
    submitGeneration += 1;
    data.value = initial;
    state.value = "idle";
    errorCode.value = null;
    errorMessage.value = null;
    submitting.value = false;
  }

  return { data, state, errorCode, errorMessage, submitting, run, submit, reset };
}
