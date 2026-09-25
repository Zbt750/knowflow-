<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppIcon from "./components/AppIcon.vue";
import ErrorBoundary from "./components/ErrorBoundary.vue";
import SystemStatus from "./components/SystemStatus.vue";

const route = useRoute();

const navItems = [
  { to: "/study", label: "今日学习", icon: "study" as const },
  { to: "/knowledge", label: "知识树", icon: "knowledge" as const },
  { to: "/materials", label: "资料库", icon: "materials" as const },
  { to: "/chat", label: "问答", icon: "chat" as const },
];

const currentPage = computed(() => route.path.startsWith("/settings")
  ? { label: "设置" }
  : navItems.find((item) => route.path.startsWith(item.to)) ?? navItems[0]);

watch(() => currentPage.value.label, (label) => {
  document.title = `${label} · 考研知识库`;
}, { immediate: true });

const DEFAULT_SIDEBAR_WIDTH = 196;
const MIN_SIDEBAR_WIDTH = 160;
const MAX_SIDEBAR_WIDTH = 360;
const COLLAPSED_SIDEBAR_WIDTH = 72;
const SIDEBAR_WIDTH_KEY = "kaoyan.sidebar.width.v1";
const SIDEBAR_COLLAPSED_KEY = "kaoyan.sidebar.collapsed.v1";

function clampSidebarWidth(width: number): number {
  return Math.round(Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, width)));
}

function readSidebarWidth(): number {
  try {
    const saved = Number(window.localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(saved) && saved > 0 ? clampSidebarWidth(saved) : DEFAULT_SIDEBAR_WIDTH;
  } catch {
    return DEFAULT_SIDEBAR_WIDTH;
  }
}

function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

const sidebarWidth = ref(readSidebarWidth());
const isSidebarCollapsed = ref(readSidebarCollapsed());
const isSidebarResizing = ref(false);
const appFrameStyle = computed(() => ({
  "--sidebar-width": `${isSidebarCollapsed.value ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth.value}px`,
}));
let resizeStartX = 0;
let resizeStartWidth = DEFAULT_SIDEBAR_WIDTH;

function startSidebarResize(event: PointerEvent): void {
  if (window.matchMedia("(max-width: 620px)").matches || event.button !== 0) return;
  event.preventDefault();
  resizeStartX = event.clientX;
  resizeStartWidth = sidebarWidth.value;
  isSidebarResizing.value = true;
  document.body.classList.add("sidebar-resizing");
  window.addEventListener("pointermove", updateSidebarResize);
  window.addEventListener("pointerup", stopSidebarResize, { once: true });
  window.addEventListener("pointercancel", stopSidebarResize, { once: true });
}

function updateSidebarResize(event: PointerEvent): void {
  if (!isSidebarResizing.value) return;
  sidebarWidth.value = clampSidebarWidth(resizeStartWidth + event.clientX - resizeStartX);
}

function saveSidebarWidth(): void {
  try {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth.value));
  } catch {
    // Storage may be disabled; resizing still works for the current page view.
  }
}

function stopSidebarResize(): void {
  if (!isSidebarResizing.value) return;
  isSidebarResizing.value = false;
  document.body.classList.remove("sidebar-resizing");
  window.removeEventListener("pointermove", updateSidebarResize);
  window.removeEventListener("pointerup", stopSidebarResize);
  window.removeEventListener("pointercancel", stopSidebarResize);
  saveSidebarWidth();
}

function resizeSidebarWithKeyboard(event: KeyboardEvent): void {
  let nextWidth = sidebarWidth.value;
  if (event.key === "ArrowLeft") nextWidth -= 16;
  else if (event.key === "ArrowRight") nextWidth += 16;
  else if (event.key === "Home") nextWidth = MIN_SIDEBAR_WIDTH;
  else if (event.key === "End") nextWidth = MAX_SIDEBAR_WIDTH;
  else return;
  event.preventDefault();
  sidebarWidth.value = clampSidebarWidth(nextWidth);
  saveSidebarWidth();
}

function resetSidebarWidth(): void {
  sidebarWidth.value = DEFAULT_SIDEBAR_WIDTH;
  saveSidebarWidth();
}

function toggleSidebarCollapsed(): void {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(isSidebarCollapsed.value));
  } catch {
    // Storage may be disabled; the toggle still works for the current page view.
  }
}

onBeforeUnmount(stopSidebarResize);
</script>

<template>
  <div class="app-frame" :class="{ 'app-frame--resizing': isSidebarResizing, 'app-frame--sidebar-collapsed': isSidebarCollapsed }" :style="appFrameStyle">
    <aside class="app-sidebar">
      <div class="sidebar-top">
        <button
          class="sidebar-toggle"
          type="button"
          :aria-label="isSidebarCollapsed ? '展开导航栏' : '收起导航栏'"
          :title="isSidebarCollapsed ? '展开导航栏' : '收起导航栏'"
          @click="toggleSidebarCollapsed"
        >
          <AppIcon :name="isSidebarCollapsed ? 'sidebar-expand' : 'sidebar-collapse'" :size="18" />
        </button>
        <RouterLink class="brand" to="/study" aria-label="考研知识库，前往今日学习">
          <strong>考研知识库</strong>
        </RouterLink>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :aria-label="item.label === '资料库' ? '资料' : item.label"
          :title="item.label"
        >
          <AppIcon :name="item.icon" :size="19" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div v-show="route.path.startsWith('/chat')" id="chat-sidebar-slot" aria-label="问答会话导航"></div>

      <div class="sidebar-footer">
        <RouterLink to="/settings" class="settings-link" aria-label="设置" title="设置">
          <AppIcon name="settings" :size="19" />
        </RouterLink>
      </div>

      <div
        class="sidebar-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整侧栏宽度，双击恢复默认"
        title="拖动调整侧栏宽度；双击恢复默认"
        :aria-valuenow="sidebarWidth"
        :aria-valuemin="MIN_SIDEBAR_WIDTH"
        :aria-valuemax="MAX_SIDEBAR_WIDTH"
        tabindex="0"
        @pointerdown="startSidebarResize"
        @keydown="resizeSidebarWithKeyboard"
        @dblclick.prevent="resetSidebarWidth"
      ></div>
    </aside>

    <div class="app-main">
      <header class="app-header">
        <strong>{{ currentPage.label }}</strong>
        <SystemStatus />
      </header>

      <main class="workspace-main" :class="{ 'workspace-main--chat': route.path.startsWith('/chat') }">
        <h1 class="sr-only">{{ currentPage.label }}</h1>
        <RouterView v-slot="{ Component }">
          <ErrorBoundary>
            <KeepAlive :include="['ChatPage']">
              <component :is="Component" />
            </KeepAlive>
          </ErrorBoundary>
        </RouterView>
      </main>
    </div>
  </div>
</template>
