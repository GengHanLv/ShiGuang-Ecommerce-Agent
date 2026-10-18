<script setup lang="ts">
import { ref, nextTick } from 'vue'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'
const props = defineProps<{ busy: boolean; disabled?: boolean }>()
const emit = defineEmits<{ send: [content: string]; stop: [] }>()
const text = ref('')
const input = ref<HTMLTextAreaElement>()
function submit() {
  if (props.busy || props.disabled || !text.value.trim()) return
  emit('send', text.value.trim())
  text.value = ''
  nextTick(resize)
}
function resize() {
  if (input.value) {
    input.value.style.height = 'auto'
    input.value.style.height = Math.min(input.value.scrollHeight, 160) + 'px'
  }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}
function fill(content: string) {
  text.value = content
  input.value?.focus()
  requestAnimationFrame(resize)
}
defineExpose({ fill })
</script>
<template>
  <div class="composer-wrap">
    <div class="composer" :class="{ disabled }">
      <textarea
        ref="input"
        v-model="text"
        maxlength="2000"
        :disabled="disabled"
        rows="1"
        placeholder="告诉拾光，你想了解什么…"
        aria-label="输入消息"
        @input="resize"
        @keydown="keydown"
      ></textarea>
      <div class="composer-toolbar">
        <div class="composer-mode">
          <BrandMark small /><span>拾光助手</span
          ><span class="mode-tag">{{
            busy ? '正在回应' : '用心为你解答'
          }}</span>
        </div>
        <div class="composer-actions">
          <span class="character-count" v-if="text.length > 1600"
            >{{ text.length }}/2000</span
          ><span class="enter-hint">Shift + Enter 换行</span
          ><button
            v-if="busy"
            class="send-button stop-button"
            aria-label="停止生成"
            @click="emit('stop')"
          >
            <span></span></button
          ><button
            v-else
            class="send-button"
            :disabled="disabled || !text.trim()"
            aria-label="发送消息"
            @click="submit"
          >
            <AppIcon name="Top" :size="21" />
          </button>
        </div>
      </div>
    </div>
    <div class="composer-footer">
      <span>由 AI 生成的回答仅供参考，订单与政策请以实际信息为准</span
      ><span>拾光 SERVICE STUDIO</span>
    </div>
  </div>
</template>
