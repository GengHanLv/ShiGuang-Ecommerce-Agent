<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BrandMark from '@/components/BrandMark.vue'
import ChatComposer from '@/components/ChatComposer.vue'
import MessageBubble from '@/components/MessageBubble.vue'
import ContextPanel from '@/components/ContextPanel.vue'
import { useChatStore } from '@/stores/chat'
import { useConnectionStore } from '@/stores/connection'
const chat = useChatStore()
const connection = useConnectionStore()
const router = useRouter()
const scrollArea = ref<HTMLElement>()
const composer = ref<InstanceType<typeof ChatComposer>>()
const followBottom = ref(true)
const suggestions = [
  {
    icon: 'Box',
    title: '订单到哪里了？',
    description: '查询订单状态，安心等候好物',
    message: '查一下我的订单',
    tone: 'green',
  },
  {
    icon: 'Collection',
    title: '想更了解一件好物',
    description: '商品参数、功能，一问便知',
    message: '演示蓝牙耳机的续航和降噪功能是什么？',
    tone: 'orange',
  },
  {
    icon: 'Service',
    title: '售后也能很省心',
    description: '退换货与服务政策，为你解答',
    message: '演示店铺怎么申请退货？',
    tone: 'purple',
  },
  {
    icon: 'Clock',
    title: '记住我的小偏好',
    description: '记下收货习惯，让服务更贴心',
    message: '记住我以后都晚上收货',
    tone: 'blue',
  },
] as const
async function send(content: string) {
  followBottom.value = true
  await chat.send(content)
}
function onScroll() {
  const el = scrollArea.value
  if (el)
    followBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 100
}
watch(
  () => chat.active?.messages.map((m) => m.content).join(''),
  async () => {
    await nextTick()
    if (scrollArea.value && followBottom.value)
      scrollArea.value.scrollTop = chat.active?.messages.length
        ? scrollArea.value.scrollHeight
        : 0
  },
)
watch(
  () => chat.activeId,
  async () => {
    followBottom.value = true
    await nextTick()
    if (scrollArea.value)
      scrollArea.value.scrollTop = chat.active?.messages.length
        ? scrollArea.value.scrollHeight
        : 0
  },
)
</script>
<template>
  <div class="chat-page">
    <section class="chat-workspace">
      <div class="conversation-heading">
        <div>
          <span class="workspace-label"><i></i> YOUR SERVICE COMPANION</span>
          <h1>{{ chat.active?.title || '把问题交给拾光' }}</h1>
        </div>
        <el-tooltip content="开启全新对话"
          ><button
            class="icon-button heading-action"
            aria-label="开启全新对话"
            @click="chat.newConversation()"
          >
            <AppIcon name="Plus" :size="20" /></button
        ></el-tooltip>
      </div>
      <div v-if="!connection.apiKey" class="setup-banner">
        <AppIcon name="Connection" :size="17" /><span
          >一切准备就绪，连接你的客服服务即可开始</span
        ><button @click="router.push('/settings')">
          去连接<AppIcon name="Right" :size="15" />
        </button>
      </div>
      <div ref="scrollArea" class="conversation-scroll" @scroll="onScroll">
        <div v-if="!chat.active?.messages.length" class="welcome-screen">
          <div class="welcome-art">
            <div class="orbit orbit-one"></div>
            <div class="orbit orbit-two"></div>
            <span class="art-dot dot-one"></span
            ><span class="art-dot dot-two"></span><BrandMark /><span
              class="mini-star"
              >✧</span
            >
          </div>
          <div class="welcome-kicker">很高兴，在这里遇见你</div>
          <h2>你好，今天有什么可以帮你？</h2>
          <p class="welcome-description">
            从一件好物，到一次安心的售后<br />你的每个问题，拾光都在认真听。
          </p>
          <div class="suggestion-grid">
            <button
              v-for="item in suggestions"
              :key="item.title"
              class="suggestion-card"
              @click="composer?.fill(item.message)"
            >
              <span class="suggestion-icon" :class="item.tone"
                ><AppIcon :name="item.icon" :size="22" /></span
              ><strong
                >{{ item.title
                }}<AppIcon name="ArrowRight" :size="14" /></strong
              ><span class="suggestion-description">{{
                item.description
              }}</span>
            </button>
          </div>
          <div class="quick-prompts">
            <span>也可以试试</span
            ><button @click="composer?.fill('你能帮我做什么？')">
              你能帮我做什么？</button
            ><button @click="composer?.fill('发货一般需要多久？')">
              发货一般要多久？
            </button>
          </div>
        </div>
        <div v-else class="messages">
          <div class="conversation-date">
            {{
              new Date(chat.active.messages[0]!.time).toLocaleDateString(
                'zh-CN',
                { month: 'long', day: 'numeric' },
              )
            }}<span>·</span>和拾光的一次沟通
          </div>
          <MessageBubble
            v-for="message in chat.active.messages"
            :key="message.id"
            :message="message"
          />
          <div v-if="chat.lastReply?.state === 'error'" class="chat-error-help">
            <router-link to="/settings">检查连接设置</router-link
            ><span>确认服务后，可重新输入问题</span>
          </div>
        </div>
      </div>
      <ChatComposer
        ref="composer"
        :busy="chat.busy"
        :disabled="!connection.apiKey"
        @send="send"
        @stop="chat.stop()"
      />
    </section>
    <ContextPanel />
  </div>
</template>
