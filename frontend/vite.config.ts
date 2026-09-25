import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig(() => {
  // E2E 通过环境变量把浏览器的相对 /api 请求代理到隔离后端；普通开发仍是 8000。
  // 不能让 fixture 自己查 8001、页面却经 5173 悄悄写到 8000。
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
  return {
    plugins: [vue()],
    resolve: {
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
