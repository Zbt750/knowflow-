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
    // Keep old bookmarks working, but route the user into the shared learning surface.
    { path: "/training", redirect: to => ({
      path: "/study",
      query: to.query.training_id && to.query.owner_session_id ? { ...to.query, mode: "personal" } : {},
    }) },
    { path: "/knowledge", component: KnowledgePage },
    { path: "/knowledge/:code/lesson", component: KnowledgeLessonPage },
    { path: "/materials", component: MaterialsPage },
    { path: "/materials/qa", redirect: to => ({ path: "/materials", query: {
      material_ids: to.query.material_ids ?? to.query.material_id,
    } }) },
    { path: "/chat", component: ChatPage },
    { path: "/settings", component: SettingsPage },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('./pages/NotFoundPage.vue') },
  ],
});
