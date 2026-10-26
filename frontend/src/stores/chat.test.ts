import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore } from './chat'
import { sendChat, streamChat } from '@/api/chat'
import { http } from '@/api/http'

vi.mock('./connection', () => ({
  useConnectionStore: () => ({ userId: 'owner', stream: true }),
}))
vi.mock('@/api/chat', () => ({ sendChat: vi.fn(), streamChat: vi.fn() }))
vi.mock('@/api/http', () => ({
  http: { post: vi.fn() },
  errorMessage: (error: Error) => error.message,
}))

describe('task recovery', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.stubGlobal('window', { addEventListener: vi.fn() })
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() })
    setActivePinia(createPinia())
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('reuses the request identity when disconnected before receiving a run ID', async () => {
    vi.mocked(streamChat).mockRejectedValue(new Error('disconnected'))
    const store = useChatStore()
    await store.send('查询商品')
    const payload = vi.mocked(streamChat).mock.calls[0]![0]
    const reply = store.active!.messages.at(-1)!
    expect(reply.runId).toBeUndefined()
    vi.mocked(sendChat).mockResolvedValue({
      reply: '已完成',
      session_id: payload.session_id!,
      run_id: 'saved-run',
      intents: [],
      memory_hits: [],
      documents: [
        {
          id: 'a'.repeat(64),
          title: '咨询总结',
          format: 'pdf',
          download_url: `/documents/${'a'.repeat(64)}/download`,
          created: 1,
        },
      ],
    })
    await store.resume(reply.id)
    expect(sendChat).toHaveBeenCalledWith(payload, expect.any(AbortSignal))
    expect(store.active!.messages).toHaveLength(2)
    expect(reply.runId).toBe('saved-run')
    expect(reply.state).toBe('done')
    expect(reply.documents?.[0]?.title).toBe('咨询总结')
    expect(http.post).not.toHaveBeenCalled()
  })

  it('does not resubmit a server-declared nonretryable operation', async () => {
    vi.mocked(streamChat).mockImplementation(
      async (_payload, _signal, onEvent) => {
        onEvent({
          type: 'error',
          content: '需要核对',
          session_id: 's',
          run_id: 'r',
          retryable: false,
        })
      },
    )
    const store = useChatStore()
    await store.send('查询商品')
    await store.resume(store.active!.messages.at(-1)!.id)
    expect(sendChat).not.toHaveBeenCalled()
    expect(http.post).not.toHaveBeenCalled()
  })
})
