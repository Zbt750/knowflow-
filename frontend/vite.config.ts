import { fileURLToPath, URL } from "node:url";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig(() => {
  // E2E 通过环境变量把浏览器的相对 /api 请求代理到隔离后端；普通开发仍是 8000。
  // 不能让 fixture 自己查 8001、页面却经 5173 悄悄写到 8000。
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
  // Codex's constrained Windows runner can return EPERM from
  // fs.realpathSync.native even for ordinary files under the workspace.
  // Vite otherwise caches that capability check and then fails to transform
  // every source file. The isolated station contains no symlinked app source;
  // keep this resolution behavior scoped to that explicit test process only.
  const isolatedUiStation = process.env.APP_ENV === "test"
    && Boolean(process.env.NAIWA_UI_TEST_STATION_ID);
  const sourcePath = fileURLToPath(new URL('./src/components/HomeRecommendationAssistant.vue', import.meta.url));
  const sourceHash = () => createHash('sha256').update(readFileSync(sourcePath)).digest('hex');
  const startupHash = sourceHash();
  return {
    plugins: [vue(), {
      name: 'naiwa-local-runtime-diagnostics',
      configureServer(server) {
        server.middlewares.use('/__naiwa_dev_runtime', (req, res, next) => {
          if (req.method !== 'GET') return next();
          let origin = 'invalid-proxy-target';
          try { origin = new URL(apiProxyTarget).origin; } catch { /* no config value leak */ }
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.setHeader('Cache-Control', 'no-store');
          res.end(JSON.stringify({ diagnostic_version: 'home-contract-runtime-v1',
            api_proxy_origin: origin, frontend_source_at_startup: startupHash,
            frontend_source_currently_served: sourceHash(),
            note: 'Dev source fingerprints; reload the browser to load its current module.' }));
        });
      },
    }],
    resolve: {
      ...(isolatedUiStation ? { preserveSymlinks: true } : {}),
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      proxy: {
        // 前端永远请求相对 /api；开发期由 Vite 代理，部署期由 Nginx 代理。
        "/api": apiProxyTarget,
      },
      watch: {
        // Playwright 在加载 ESM 测试文件时，会在测试文件所在目录创建
        // `<file>.tmpdir/<file>.tmp` 这种一次性目录。Windows 上这些临时文件处于被占用状态，
        // Vite 若监视它们会抛 EBUSY 并直接杀掉开发服务器。
        // 因此这里必须排除所有临时目录与测试产物，而不只是 frontend 根目录下的那一层。
        ignored: [
          "**/*.tmpdir/**",
          "**/*tmpdir*/**",
          "**/.playwright*/**",
          "**/test-results/**",
          "**/playwright-report/**",
          "**/blob-report/**",
        ],
      },
    },
  };
});
