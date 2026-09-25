import { createApp } from "vue";

import App from "./App.vue";
import { reportGlobalFailure } from "./lib/runtimeErrors";
import { router } from "./router";
import "./styles.css";

const app = createApp(App);

// ErrorBoundary 处理页面级异常；这里兜住边界本身或异步回调遗漏的异常。
app.config.errorHandler = (error, _instance, info) => {
  reportGlobalFailure(error, info);
};

app.use(router).mount("#app");