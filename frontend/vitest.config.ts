import { defineConfig } from "vitest/config";
import vue from '@vitejs/plugin-vue';

// These tests mount Vue on an in-memory renderer, not the SSR renderer.
// Node's default SSR transform otherwise emits ssrRender/useSSRContext.
const componentPlugin = vue();
const transform = componentPlugin.transform;
if (typeof transform === 'function') componentPlugin.transform = function(code, id, options) {
  return transform.call(this, code, id, {...options, ssr: false});
};

const isolatedUiStation = process.env.APP_ENV === "test"
  && Boolean(process.env.NAIWA_UI_TEST_STATION_ID);

export default defineConfig({
  plugins: [componentPlugin],
  resolve: isolatedUiStation ? { preserveSymlinks: true } : undefined,
  test: { include: ["src/**/*.test.ts"], environment: "node", clearMocks: true },
});
