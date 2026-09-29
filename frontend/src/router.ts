import { createRouter, createWebHistory } from "vue-router";

const ChatPage = () => import("./pages/ChatPage.vue");
const KnowledgePage = () => import("./pages/KnowledgePage.vue");
const KnowledgeLessonPage = () => import("./pages/KnowledgeLessonPage.vue");
const MaterialsPage = () => import("./pages/MaterialsPage.vue");
const StudyPage = () => import("./pages/StudyPage.vue");
const SettingsPage = () => import("./pages/SettingsPage.vue");

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/study" },
    { path: "/study", component: StudyPage },
    { path: "/knowledge", component: KnowledgePage },
    { path: "/knowledge/:code/lesson", component: KnowledgeLessonPage },
    { path: "/materials", component: MaterialsPage },
    { path: "/chat", component: ChatPage },
    { path: "/settings", component: SettingsPage },
  ],
});
