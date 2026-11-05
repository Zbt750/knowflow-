import { createApp } from "vue";

import App from "./App.vue";
import { reportGlobalFailure } from "./lib/runtimeErrors";
import { router } from "./router";
import "./styles.css";
import "./product-theme.css";
import "katex/dist/katex.min.css";
import mainMathFont from "katex/dist/fonts/KaTeX_Main-Regular.woff2?url";
import italicMathFont from "katex/dist/fonts/KaTeX_Math-Italic.woff2?url";
// 提前加载最常见的正文/变量字体，不隐藏公式、不等待模型返回才下载。
for (const href of [mainMathFont, italicMathFont]) {
  const link = document.createElement("link");
  link.rel = "preload"; link.as = "font"; link.type = "font/woff2";
  link.crossOrigin = "anonymous"; link.href = href;
  document.head.appendChild(link);
}

const app = createApp(App);

// ErrorBoundary 处理页面级异常；这里兜住边界本身或异步回调遗漏的异常。
app.config.errorHandler = (error, _instance, info) => {
  reportGlobalFailure(error, info);
};

app.use(router).mount("#app");
