<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import AppIcon from '@/components/AppIcon.vue'
import BrandMark from '@/components/BrandMark.vue'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { useServiceStatus } from '@/composables/useServiceStatus'
const route = useRoute()
const router = useRouter()
const chat = useChatStore()
const auth = useAuthStore()
const mobileOpen = ref(false)
const query = ref('')
const searchOpen = ref(false)
const { state, refresh } = useServiceStatus()
const conversations = computed(() =>
  chat.list.filter((c) =>
    c.title.toLowerCase().includes(query.value.toLowerCase()),
  ),
)
const nav = [
  { name: 'chat', path: '/', label: '智能对话', icon: 'ChatLineRound' },
  {
    name: 'knowledge',
    path: '/knowledge',
    label: '知识中心',
    icon: 'Collection',
  },
  { name: 'settings', path: '/settings', label: '连接设置', icon: 'Setting' },
] as const
function newChat() {
  chat.newConversation()
  router.push('/')
  mobileOpen.value = false
}
function select(id: string) {
  chat.activeId = id
  router.push('/')
  mobileOpen.value = false
}
async function remove(id: string) {
  try {
    await ElMessageBox.confirm(
      '这段对话的本地记录将被删除，后端记忆不受影响。',
      '删除对话',
      { confirmButtonText: '删除', cancelButtonText: '保留', type: 'warning' },
    )
    chat.remove(id)
  } catch {
    /* canceled */
  }
}
function handleShortcut(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (event.key === 'Escape') mobileOpen.value = false
  if (target?.matches('input, textarea, select, [contenteditable="true"]'))
    return
  if (
    event.key.toLowerCase() === 'n' &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  ) {
    event.preventDefault()
    newChat()
  }
}
onMounted(() => window.addEventListener('keydown', handleShortcut))
onBeforeUnmount(() => window.removeEventListener('keydown', handleShortcut))
</script>
<template>
  <div class="workspace">
    <div
      v-if="mobileOpen"
      class="sidebar-overlay"
      @click="mobileOpen = false"
    ></div>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <router-link class="brand" to="/" @click="mobileOpen = false"
        ><BrandMark /><span class="brand-word"
          >拾光<span class="brand-en">SERVICE STUDIO</span></span
        ><span class="brand-badge">AI</span></router-link
      >
      <button class="new-chat" @click="newChat">
        <AppIcon name="Plus" :size="19" /><span>开启新对话</span
        ><span class="keycap">N</span>
      </button>
      <nav class="navigation" aria-label="工作台导航">
        <router-link
          v-for="item in nav"
          :key="item.name"
          :to="item.path"
          :class="{ active: route.name === item.name }"
          @click="mobileOpen = false"
          ><AppIcon :name="item.icon" :size="19" /><span>{{ item.label }}</span
          ><span v-if="item.name === 'chat'" class="nav-dot"></span
        ></router-link>
      </nav>
      <div class="sidebar-divider"></div>
      <div class="history-heading">
        <span>最近对话</span
        ><button
          class="icon-button"
          aria-label="搜索对话"
          @click="searchOpen = !searchOpen"
        >
          <AppIcon name="Search" :size="16" />
        </button>
      </div>
      <el-input
        v-if="searchOpen"
        v-model="query"
        class="history-search"
        placeholder="搜索对话标题"
        clearable
        size="small"
        aria-label="搜索对话标题"
      />
      <div class="history-list">
        <div v-if="!conversations.length" class="history-empty">
          <AppIcon name="ChatLineRound" :size="23" />
          <p>{{ query ? '没有找到相关对话' : '故事从一次对话开始' }}</p>
          <span v-if="!query">你的最近对话会出现在这里</span>
        </div>
        <div
          v-for="item in conversations"
          :key="item.id"
          class="history-item"
          :class="{
            selected: chat.activeId === item.id && route.name === 'chat',
          }"
        >
          <button class="history-select" @click="select(item.id)">
            <AppIcon name="ChatLineRound" :size="15" /><span>{{
              item.title
            }}</span></button
          ><button
            class="icon-button delete-conversation"
            :disabled="chat.pendingId === item.id"
            :aria-label="`删除对话：${item.title}`"
            @click="remove(item.id)"
          >
            <AppIcon name="Close" :size="13" />
          </button>
        </div>
      </div>
      <router-link class="profile" to="/settings"
        ><span class="avatar">{{
          (auth.user?.username || '').slice(0, 1).toUpperCase()
        }}</span
        ><span
          ><strong>{{ auth.user?.username || '' }}</strong
          ><small>当前体验用户</small></span
        ><AppIcon name="Setting" :size="17"
      /></router-link>
    </aside>
    <section class="workspace-main">
      <header class="topbar">
        <div class="page-title">
          <button
            class="icon-button mobile-toggle"
            aria-label="展开导航"
            @click="mobileOpen = true"
          >
            <AppIcon name="Menu" /></button
          ><span>工作空间</span><span class="breadcrumb-slash">/</span
          ><strong>{{ route.meta.title }}</strong>
        </div>
        <div class="topbar-actions">
          <button
            class="connection-status"
            :class="state"
            @click="refresh"
            aria-label="重新检测后端连接"
          >
            <i></i
            >{{
              state === 'online'
                ? '服务已连接'
                : state === 'checking'
                  ? '正在连接'
                  : '服务未连接'
            }}</button
          ><span class="topbar-separator"></span
          ><router-link
            class="icon-button"
            to="/settings"
            aria-label="打开连接设置"
            ><AppIcon name="Setting" :size="19" /></router-link
          ><span class="small-avatar">{{
            (auth.user?.username || '').slice(0, 1).toUpperCase()
          }}</span>
        </div>
      </header>
      <main class="page-content">
        <router-view v-slot="{ Component }"
          ><transition name="page" mode="out-in"
            ><component :is="Component" /></transition
        ></router-view>
      </main>
    </section>
  </div>
</template>
