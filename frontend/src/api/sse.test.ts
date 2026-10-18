import { describe, it, expect } from 'vitest'
import { consumeSSE } from './sse'
function stream(parts: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      parts.forEach((part) => controller.enqueue(part))
      controller.close()
    },
  })
}
describe('SSE transport', () => {
  it('preserves multibyte characters split between network chunks', async () => {
    const raw = new TextEncoder().encode(
      'data: {"type":"token","content":"你好"}\n\ndata: {"type":"done"}\n\n',
    )
    const events: string[] = []
    await consumeSSE(
      stream(Array.from(raw, (byte) => new Uint8Array([byte]))),
      (value) => events.push(value),
    )
    expect(events.map((e) => JSON.parse(e))).toEqual([
      { type: 'token', content: '你好' },
      { type: 'done' },
    ])
  })
  it('supports CRLF, comments and multiline data', async () => {
    const events: string[] = []
    await consumeSSE(
      stream([
        new TextEncoder().encode(
          ': keepalive\r\ndata: first\r\ndata: second\r\n\r\n',
        ),
      ]),
      (value) => events.push(value),
    )
    expect(events).toEqual(['first\nsecond'])
  })
  it('flushes the last buffered event on EOF', async () => {
    const events: string[] = []
    await consumeSSE(
      stream([new TextEncoder().encode('data: final')]),
      (value) => events.push(value),
    )
    expect(events).toEqual(['final'])
  })
})
