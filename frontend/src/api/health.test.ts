import { afterEach, expect, it, vi } from "vitest";
import { fetchHealth } from "./health";

afterEach(() => vi.unstubAllGlobals());

it("preserves pending retrieval probe reason for the settings status", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    status: "ok",
    database: "connected",
    environment: "test",
    retrieval: "unavailable",
    retrieval_reason: "dependency_probe_pending",
    worker: "running",
    llm_configured: false,
    llm_model: null,
  }), { status: 200, headers: { "content-type": "application/json" } })));

  await expect(fetchHealth()).resolves.toMatchObject({
    retrieval: "unavailable",
    retrieval_reason: "dependency_probe_pending",
  });
});
