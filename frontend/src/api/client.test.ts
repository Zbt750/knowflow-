import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.unstubAllGlobals());
it("shows field-specific safe validation guidance", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "validation_failed", message: "validation failed", details: [{ field: "query.limit", code: "greater_than_equal", message: "应大于或等于 1" }] } }), { status: 422 })));
  await expect(api.get("/api/materials")).rejects.toMatchObject({ code: "validation_failed", message: "limit：应大于或等于 1" });
});
it("supports legacy validation without exposing raw detail", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: [{ input: "secret" }] }), { status: 422 })));
  await expect(api.get("/api/test")).rejects.toMatchObject({ message: "请求参数不符合要求" });
});
it("handles empty 204 response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
  await expect(api.delete("/api/test")).resolves.toBeUndefined();
});
it("distinguishes network failure from explicit cancellation", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
  await expect(api.get("/api/test")).rejects.toBeInstanceOf(ApiError);
  const abort = new DOMException("cancel", "AbortError");
  vi.stubGlobal("fetch", vi.fn(async () => { throw abort; }));
  await expect(api.get("/api/test")).rejects.toBe(abort);
});
it("passes abort signals through multipart uploads", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  await api.upload("/api/materials", new FormData(), controller.signal);
  expect(fetch.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: controller.signal }));
});
it("sends settings token as a header, not URL", async () => {
  const fetch = vi.fn(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await api.put("/api/settings/model", { model: "test" }, { "X-Settings-Token": "token" });
  expect(fetch.mock.calls[0]).toEqual(["/api/settings/model", expect.objectContaining({ headers: expect.objectContaining({ "X-Settings-Token": "token" }) })]);
});
