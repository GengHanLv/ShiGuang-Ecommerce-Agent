import { http } from './http'
import { consumeSSE } from './sse'
import type { ChatPayload, ChatResult, StreamEvent } from '@/types'
export async function sendChat(payload: ChatPayload, signal: AbortSignal) {
  return (
    await http.post<ChatResult>('/chat', payload, { signal, timeout: 300000 })
  ).data
}
export async function streamChat(
  payload: ChatPayload,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
) {
  const response = await http.post<ReadableStream<Uint8Array>>(
    '/chat/stream',
    payload,
    {
      signal,
      adapter: 'fetch',
      responseType: 'stream',
      timeout: 300000,
    },
  )
  let completed = false
  await consumeSSE(response.data, (data) => {
    const event = JSON.parse(data) as StreamEvent
    if (event.type === 'done' || event.type === 'error') completed = true
    onEvent(event)
  })
  if (!completed) throw new Error('连接中断，回复尚未完成，请重新发送')
}
