import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useConnectionStore } from './connection'
import { sendChat, streamChat } from '@/api/chat'
import { errorMessage } from '@/api/http'
import type { Conversation, Message, ChatResult } from '@/types'
export const useChatStore = defineStore('chat', () => {
  const connection = useConnectionStore()
  let initial: Conversation[] = []
  try {
    const saved = JSON.parse(
      localStorage.getItem('shiguang.conversations') || '[]',
    )
    if (Array.isArray(saved))
      initial = saved
        .filter(
          (c) =>
            c &&
            typeof c.id === 'string' &&
            typeof c.userId === 'string' &&
            typeof c.updatedAt === 'string' &&
            typeof c.sessionId === 'string' &&
            typeof c.title === 'string' &&
            Array.isArray(c.messages),
        )
        .slice(0, 50)
        .map((c) => ({
          ...c,
          messages: c.messages
            .filter(
              (m: Message) =>
                m &&
                typeof m.content === 'string' &&
                typeof m.time === 'string' &&
                !Number.isNaN(Date.parse(m.time)) &&
                ['user', 'assistant'].includes(m.role),
            )
            .map((m: Message) => ({
              ...m,
              state: m.state === 'pending' ? 'stopped' : m.state,
            })),
        }))
  } catch {
    /* use empty history */
  }
  const conversations = ref<Conversation[]>(initial)
  const activeId = ref('')
  const pendingId = ref('')
  let controller: AbortController | undefined
  const list = computed(() =>
    conversations.value
      .filter((c) => c.userId === connection.userId)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
  )
  const active = computed(() => list.value.find((c) => c.id === activeId.value))
  const busy = computed(() => !!pendingId.value)
  const lastReply = computed(() =>
    active.value?.messages.filter((m) => m.role === 'assistant').at(-1),
  )
  watch(
    () => connection.userId,
    () => {
      controller?.abort()
      activeId.value = ''
    },
  )
  let persistenceTimer: ReturnType<typeof setTimeout> | undefined
  function persistHistory() {
    try {
      const records = conversations.value
        .slice(-50)
        .map((c) => ({ ...c, messages: c.messages.slice(-100) }))
      localStorage.setItem('shiguang.conversations', JSON.stringify(records))
    } catch {
      /* quota exceeded; current session remains in memory */
    }
  }
  // Avoid synchronously serializing history on every streamed token.
  watch(
    conversations,
    () => {
      clearTimeout(persistenceTimer)
      persistenceTimer = setTimeout(persistHistory, 300)
    },
    { deep: true },
  )
  window.addEventListener('pagehide', persistHistory)
  function newConversation() {
    activeId.value = ''
  }
  function remove(id: string) {
    if (id === pendingId.value) return
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeId.value === id) activeId.value = ''
  }
  function clear() {
    conversations.value = conversations.value.filter(
      (c) => c.userId !== connection.userId || c.id === pendingId.value,
    )
    if (activeId.value !== pendingId.value) activeId.value = ''
  }
  async function send(content: string) {
    if (busy.value || !content.trim()) return
    let conversation = active.value
    if (!conversation) {
      const now = new Date().toISOString()
      const record: Conversation = {
        id: crypto.randomUUID(),
        sessionId: crypto.randomUUID(),
        userId: connection.userId,
        title: content.slice(0, 20),
        updatedAt: now,
        messages: [],
      }
      conversations.value.push(record)
      activeId.value = record.id
      conversation = active.value!
    }
    conversation.updatedAt = new Date().toISOString()
    conversation.messages.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: content.trim(),
      time: new Date().toISOString(),
      state: 'done',
    })
    const reply: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      time: new Date().toISOString(),
      state: 'pending',
    }
    conversation.messages.push(reply)
    const message = conversation.messages.at(-1)!
    pendingId.value = conversation.id
    controller = new AbortController()
    const finish = (data: ChatResult) => {
      message.content = data.reply
      message.intents = data.intents || []
      message.memoryHits = data.memory_hits || []
      message.toolTrace = data.tool_trace || []
      message.stopReason = data.stop_reason
      message.productImages = data.product_images || []
      message.documents = data.documents || []
      message.runId = data.run_id || message.runId
      message.retryable = data.retryable
      message.state = data.degraded ? 'error' : 'done'
      conversation!.sessionId = data.session_id
    }
    try {
      const payload = {
        request_id: crypto.randomUUID(),
        message: content,
        session_id: conversation.sessionId,
      }
      message.requestId = payload.request_id
      if (connection.stream) {
        await streamChat(payload, controller.signal, (event) => {
          if (event.type === 'task') {
            message.runId = event.run_id
            conversation!.sessionId = event.session_id
          } else if (event.type === 'token') message.content += event.content
          else if (event.type === 'done') finish(event)
          else {
            message.content = event.content
            message.state = 'error'
            message.runId = event.run_id || message.runId
            message.retryable = event.retryable
          }
        })
      } else finish(await sendChat(payload, controller.signal))
    } catch (error) {
      if (controller.signal.aborted) {
        message.state = 'stopped'
        if (!message.content) message.content = '已停止生成'
      } else {
        message.state = 'error'
        message.content = message.content
          ? message.content + '\n\n' + errorMessage(error)
          : errorMessage(error)
      }
    } finally {
      if (message.state === 'pending') message.state = 'error'
      conversation.updatedAt = new Date().toISOString()
      pendingId.value = ''
      controller = undefined
    }
  }
  function stop() {
    controller?.abort()
  }
  async function resume(messageId: string) {
    if (busy.value || !active.value) return
    const conversation = active.value
    const message = conversation.messages.find((item) => item.id === messageId)
    if (!message || message.retryable === false) return
    const index = conversation.messages.indexOf(message)
    const question = conversation.messages[index - 1]
    if (!message.runId && (!message.requestId || question?.role !== 'user'))
      return
    pendingId.value = conversation.id
    message.state = 'pending'
    controller = new AbortController()
    try {
      const { http } = await import('@/api/http')
      const data = message.runId
        ? (
            await http.post<ChatResult>(
              `/tasks/${encodeURIComponent(message.runId)}/resume`,
              {},
              { timeout: 300000, signal: controller.signal },
            )
          ).data
        : await sendChat(
            {
              request_id: message.requestId,
              session_id: conversation.sessionId,
              message: question!.content,
            },
            controller.signal,
          )
      message.content = data.reply
      message.productImages = data.product_images || []
      message.documents = data.documents || []
      message.toolTrace = data.tool_trace || []
      message.intents = data.intents || []
      message.memoryHits = data.memory_hits || []
      message.stopReason = data.stop_reason
      message.runId = data.run_id || message.runId
      message.retryable = data.retryable
      conversation.sessionId = data.session_id
      message.state = data.degraded ? 'error' : 'done'
    } catch (error) {
      message.state = controller.signal.aborted ? 'stopped' : 'error'
      if (!controller.signal.aborted) message.content = errorMessage(error)
    } finally {
      conversation.updatedAt = new Date().toISOString()
      pendingId.value = ''
      controller = undefined
    }
  }
  return {
    conversations,
    activeId,
    list,
    active,
    busy,
    pendingId,
    lastReply,
    newConversation,
    remove,
    clear,
    send,
    stop,
    resume,
  }
})
