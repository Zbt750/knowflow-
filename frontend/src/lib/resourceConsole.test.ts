import { describe, expect, it } from "vitest";
import { isApiResourceNoise } from "../../e2e/resourceConsole";

describe("browser resource console classification", () => {
  it("allows intentionally exercised API response and connection errors", () => {
    expect(isApiResourceNoise("Failed to load resource: the server responded with a status of 500 @ http://127.0.0.1:5174/api/materials?offset=0")).toBe(true);
    expect(isApiResourceNoise("Failed to load resource: net::ERR_CONNECTION_REFUSED @ http://127.0.0.1:8001/api/plans/today")).toBe(true);
  });
  it("never dismisses static module failures or unlocated errors", () => {
    for (const text of [
      "Failed to load resource: net::ERR_NO_BUFFER_SPACE @ http://127.0.0.1:5174/src/router.ts",
      "Failed to load resource: the server responded with a status of 404 @ http://127.0.0.1:5174/assets/main.js",
      "Failed to load resource: net::ERR_FAILED",
      "TypeError: Failed to load resource: @ http://127.0.0.1/api/materials",
      "Failed to load resource: error @ invalid-url",
    ]) expect(isApiResourceNoise(text)).toBe(false);
  });
});
