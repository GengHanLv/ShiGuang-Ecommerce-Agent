<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { useChatStore } from '@/stores/chat'
import { useConnectionStore } from '@/stores/connection'
import { intentLabels } from '@/types'
const chat = useChatStore()
const connection = useConnectionStore()
</script>
<template>
  <aside class="context-panel">
    <div class="context-heading">
      <AppIcon name="Connection" :size="17" /><strong>对话洞察</strong
      ><span>LIVE</span>
    </div>
    <div class="context-section">
      <span class="eyebrow">本轮意图</span>
      <div v-if="chat.lastReply?.intents?.length" class="intent-chips">
        <span
          v-for="intent in chat.lastReply.intents"
          :key="intent"
          class="intent-chip"
          >{{ intentLabels[intent] || intent }}</span
        >
      </div>
      <div v-else class="context-placeholder">
        <span class="placeholder-line"></span
        ><span class="placeholder-line short"></span>
        <p>对话后，自动识别你的需求</p>
      </div>
    </div>
    <div class="context-section">
      <div class="context-label">
        <span class="eyebrow">记忆召回</span
        ><span class="count-tag">{{
          chat.lastReply?.memoryHits?.length || 0
        }}</span>
      </div>
      <div v-if="chat.lastReply?.memoryHits?.length" class="memory-hits">
        <p v-for="memory in chat.lastReply.memoryHits" :key="memory">
          <AppIcon name="Clock" :size="14" />{{
            memory.replace(/^\[.*?\]\s*/, '')
          }}
        </p>
      </div>
      <div v-else class="memory-empty">
        <div class="memory-symbol">
          <AppIcon name="FolderOpened" :size="25" />
        </div>
        <p>每一次了解，都有迹可循</p>
        <span>相关的收货偏好会在这里呈现</span>
      </div>
    </div>
    <div class="context-section session-info">
      <span class="eyebrow">会话信息</span>
      <dl>
        <div>
          <dt>当前用户</dt>
          <dd>{{ connection.userId }}</dd>
        </div>
        <div>
          <dt>响应方式</dt>
          <dd>
            {{ connection.stream ? '流式响应' : '完整响应'
            }}<i class="tiny-dot"></i>
          </dd>
        </div>
        <div>
          <dt>消息数量</dt>
          <dd>{{ chat.active?.messages.length || 0 }} 条</dd>
        </div>
      </dl>
    </div>
    <div class="context-tip">
      <AppIcon name="Lock" :size="17" />
      <div>
        <strong>只为你，记住偏好</strong>
        <p>告诉助手你的收货习惯，<br />下次沟通时，多一份默契。</p>
      </div>
    </div>
    <div class="context-bottom">
      <span class="decorative-spark">✳</span><span>认真倾听，温柔回应</span>
    </div>
  </aside>
</template>
