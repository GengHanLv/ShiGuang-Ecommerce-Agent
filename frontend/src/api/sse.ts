/** Incremental SSE decoding handles split UTF-8 characters, CRLF and multiline data. */
export async function consumeSSE(
  stream: ReadableStream<Uint8Array>,
  onData: (data: string) => void,
) {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let data: string[] = []
  const line = (value: string) => {
    if (value === '') {
      if (data.length) {
        onData(data.join('\n'))
        data = []
      }
    } else if (value.startsWith('data:'))
      data.push(value.slice(5).replace(/^ /, ''))
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let position: number
      while ((position = buffer.indexOf('\n')) >= 0) {
        line(buffer.slice(0, position).replace(/\r$/, ''))
        buffer = buffer.slice(position + 1)
      }
      if (done) break
    }
    if (buffer) line(buffer.replace(/\r$/, ''))
    if (data.length) onData(data.join('\n'))
  } finally {
    reader.releaseLock()
  }
}
