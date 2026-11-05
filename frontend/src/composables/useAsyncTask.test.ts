import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { StaleResponse, useAsyncTask } from "./useAsyncTask";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("useAsyncTask", () => {
  it("loads and refreshes without hiding existing data", async () => {
    const task = useAsyncTask<number>();
    await task.run(async () => 1);
    const next = deferred<number>();
    const pending = task.run(() => next.promise, { keepPreviousData: true });
    expect(task.state.value).toBe("success");
    expect(task.data.value).toBe(1);
    next.resolve(2); await pending;
    expect(task.data.value).toBe(2);
  });
  it("does not let an older success overwrite a newer result", async () => {
    const task = useAsyncTask<number>();
    const old = deferred<number>();
    const pending = task.run(() => old.promise);
    await task.run(async () => 2);
    old.resolve(1);
    expect(await pending).toBeNull();
    expect(task.data.value).toBe(2);
  });
  it("ignores an older error", async () => {
    const task = useAsyncTask<number>();
    const old = deferred<number>();
    const pending = task.run(() => old.promise);
    await task.run(async () => 2);
    old.reject(new Error("old")); await pending;
    expect(task.state.value).toBe("success");
    expect(task.errorMessage.value).toBeNull();
  });
  it("reset invalidates in-flight results", async () => {
    const task = useAsyncTask<number>();
    const request = deferred<number>();
    const pending = task.run(() => request.promise);
    task.reset(); request.resolve(3); await pending;
    expect(task.data.value).toBeNull();
    expect(task.state.value).toBe("idle");
  });
  it.each([new StaleResponse(), new DOMException("cancelled", "AbortError")])("cancellation is not an error", async (error) => {
    const task = useAsyncTask<number>();
    await task.run(async () => { throw error; });
    expect(task.state.value).toBe("idle");
    expect(task.errorMessage.value).toBeNull();
  });
  it("maps known API failures and clears them on success", async () => {
    const task = useAsyncTask<number>(null, { errorMessages: { not_found: "找不到" } });
    await task.run(async () => { throw new ApiError("raw", 404, "not_found"); });
    expect(task.errorMessage.value).toBe("找不到");
    await task.run(async () => 1);
    expect(task.errorCode.value).toBeNull();
  });
  it("uses safe fallback for non-API failures", async () => {
    const task = useAsyncTask(null, { fallbackMessage: "加载失败" });
    await task.run(async () => { throw new Error("internal secret"); });
    expect(task.errorMessage.value).toBe("加载失败");
  });
  it("prevents duplicate submission and resets busy on failure", async () => {
    const task = useAsyncTask<number>();
    const request = deferred<number>();
    const pending = task.submit(() => request.promise);
    const duplicate = vi.fn(async () => 2);
    expect(await task.submit(duplicate)).toBeNull();
    expect(duplicate).not.toHaveBeenCalled();
    request.reject(new Error("failed")); await pending;
    expect(task.submitting.value).toBe(false);
    expect(task.state.value).toBe("error");
  });
});
