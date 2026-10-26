<script setup lang="ts">
import { ref, computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { ElMessage } from 'element-plus'
import AppIcon from './AppIcon.vue'
import BrandMark from './BrandMark.vue'
import ProductGallery from './ProductGallery.vue'
import { useChatStore } from '@/stores/chat'
import { errorMessage } from '@/api/http'
import { exportTaskPdf, fetchDocumentPdf } from '@/api/documents'
import type { SavedDocument } from '@/types'
const chat = useChatStore()
import type { Message } from '@/types'
import { intentLabels } from '@/types'
const props = defineProps<{ message: Message }>()
const copied = ref(false)
const rendered = computed(() => renderMarkdown(props.message.content))
const exporting = ref(false)
const exported = ref<SavedDocument[]>([])
const documents = computed(() =>
  [...(props.message.documents || []), ...exported.value].filter(
    (d, i, rows) =>
      /^[a-f0-9]{64}$/.test(d.id) && rows.findIndex((x) => x.id === d.id) === i,
  ),
)
async function download(document: SavedDocument) {
  if (!/^[a-f0-9]{64}$/.test(document.id)) return
  try {
    const blob = await fetchDocumentPdf(document.id)
    const url = URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = `consultation-${document.id.slice(0, 12)}.pdf`
    window.document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function exportPdf() {
  if (!props.message.runId || exporting.value) return
  exporting.value = true
  try {
    const document = await exportTaskPdf(props.message.runId)
    exported.value.push(document)
    await download(document)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    exporting.value = false
  }
}
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
function sourceLink(url: string) {
  try {
    const parsed = new URL(url)
    return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username
      ? parsed.href
      : undefined
  } catch {
    return undefined
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
          <i></i><i></i><i></i><span>正在整理回复…</span>
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
        <details v-if="message.toolTrace?.length" class="processing-summary">
          <summary>
            查看处理摘要与来源（{{ message.toolTrace.length }} 次工具调用）
          </summary>
          <p>以下为实际工具执行记录和证据摘要。</p>
          <ol>
            <li v-for="(step, index) in message.toolTrace" :key="index">
              <strong>第 {{ step.step }} 轮 · {{ step.tool }}</strong>
              <span>
                · {{ step.status === 'success' ? '已返回' : '未完成' }}</span
              >
              <p v-if="step.summary">{{ step.summary }}</p>
              <ul v-if="step.sources?.length">
                <li v-for="source in step.sources" :key="source.url">
                  <a
                    :href="sourceLink(source.url)"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ source.title }}</a
                  >
                </li>
              </ul>
            </li>
          </ol>
        </details>
        <ProductGallery
          v-if="message.role === 'assistant'"
          :images="message.productImages"
        />
        <div v-if="documents.length" class="document-downloads">
          <el-button
            v-for="document in documents"
            :key="document.id"
            @click="download(document)"
          >
            下载 PDF · {{ document.title }}
          </el-button>
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
        <div class="message-actions">
          <button
            v-if="
              (message.runId || message.requestId) &&
              message.retryable !== false &&
              ['error', 'stopped'].includes(message.state || '')
            "
            class="icon-button message-text-action"
            :disabled="chat.busy"
            @click="chat.resume(message.id)"
          >
            继续处理
          </button>
          <button
            v-if="message.runId && message.state === 'done'"
            class="icon-button message-text-action"
            :disabled="exporting"
            @click="exportPdf"
          >
            {{ exporting ? '正在导出…' : '保存为 PDF' }}
          </button>
          <button
            class="icon-button"
            :aria-label="copied ? '已复制' : '复制回复'"
            @click="copy"
          >
            <AppIcon :name="copied ? 'Check' : 'CopyDocument'" :size="15" />
          </button>
        </div>
      </div>
    </div>
  </article>
</template>
