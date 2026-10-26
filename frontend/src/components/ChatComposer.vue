<script setup lang="ts">
import { ref, nextTick } from 'vue'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'
import { http, errorMessage } from '@/api/http'
import { ElMessage } from 'element-plus'
const props = defineProps<{ busy: boolean; disabled?: boolean }>()
const emit = defineEmits<{ send: [content: string]; stop: [] }>()
const text = ref('')
const creatingDemo = ref(false)
async function prepareDemo() {
  if (props.busy || props.disabled || creatingDemo.value) return
  creatingDemo.value = true
  try {
    const { data } = await http.post<{ order_id: number }>('/orders/demo')
    fill(
      `请查询我的模拟订单 ${data.order_id}，告诉我商品、金额和订单状态，并说明哪些物流信息尚未提供。`,
    )
    ElMessage.success('模拟订单已准备好，点击发送即可测试；不会产生真实购买。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    creatingDemo.value = false
  }
}
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
    <div class="demo-order-entry">
      <button
        type="button"
        class="icon-button message-text-action"
        :disabled="busy || disabled || creatingDemo"
        @click="prepareDemo"
      >
        {{ creatingDemo ? '正在准备…' : '创建模拟订单并填入测试问题' }}
      </button>
      <span>仅创建虚构测试数据</span>
    </div>
    <div class="composer-footer">
      <span>由 AI 生成的回答仅供参考，订单与政策请以实际信息为准</span
      ><span>拾光 SERVICE STUDIO</span>
    </div>
  </div>
</template>
