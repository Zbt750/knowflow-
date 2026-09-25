import { createRouter, createWebHistory } from "vue-router";

import ChatPage from "./pages/ChatPage.vue";
import KnowledgePage from "./pages/KnowledgePage.vue";
import MaterialsPage from "./pages/MaterialsPage.vue";
import StudyPage from "./pages/StudyPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/study" },
    { path: "/study", component: StudyPage },
    { path: "/knowledge", component: KnowledgePage },
    { path: "/materials", component: MaterialsPage },
    { path: "/chat", component: ChatPage },
    { path: "/settings", component: SettingsPage },
  ],
});
