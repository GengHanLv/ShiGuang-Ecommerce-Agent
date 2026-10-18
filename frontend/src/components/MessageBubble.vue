<script setup lang="ts">
import { ref, computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { ElMessage } from 'element-plus'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'
import type { Message } from '@/types'
import { intentLabels } from '@/types'
const props = defineProps<{ message: Message }>()
const copied = ref(false)
const rendered = computed(() => renderMarkdown(props.message.content))
async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}
function time(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>
<template>
  <article class="message-row" :class="message.role">
    <div class="message-avatar">
      <BrandMark v-if="message.role === 'assistant'" small /><AppIcon
        v-else
        name="Service"
        :size="18"
      />
    </div>
    <div class="message-main">
      <div class="message-meta">
        <strong>{{ message.role === 'assistant' ? '拾光助手' : '你' }}</strong
        ><span v-if="message.role === 'assistant'" class="assistant-label"
          >AI</span
        ><time>{{ time(message.time) }}</time>
      </div>
      <div
        class="message-bubble"
        :class="{ 'error-bubble': message.state === 'error' }"
      >
        <div
          v-if="message.state === 'pending' && !message.content"
          class="thinking"
        >
          <i></i><i></i><i></i><span>正在认真思考…</span>
        </div>
        <div
          v-else
          class="message-text"
          :class="{ markdown: message.role === 'assistant' }"
        >
          <div v-if="message.role === 'assistant'" v-html="rendered"></div>
          <template v-else>{{ message.content }}</template>
          <span v-if="message.state === 'pending'" class="typing-cursor"></span>
        </div>
      </div>
      <div
        class="message-bottom"
        v-if="message.role === 'assistant' && message.state !== 'pending'"
      >
        <div class="message-intents">
          <span v-for="intent in message.intents" :key="intent"
            ><i></i>{{ intentLabels[intent] || intent }}</span
          ><span v-if="message.state === 'stopped'">生成已停止</span
          ><span v-if="message.state === 'error'" class="error-text"
            >本次请求未完成</span
          >
        </div>
        <button
          class="icon-button"
          :aria-label="copied ? '已复制' : '复制回复'"
          @click="copy"
        >
          <AppIcon :name="copied ? 'Check' : 'CopyDocument'" :size="15" />
        </button>
      </div>
    </div>
  </article>
</template>
