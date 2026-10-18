import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
interface Connection {
  baseUrl: string
  apiKey: string
  userId: string
  stream: boolean
}
const defaults: Connection = {
  baseUrl: import.meta.env.VITE_API_BASE_URL || '/api',
  apiKey: '',
  userId: 'user123',
  stream: true,
}
export const useConnectionStore = defineStore('connection', () => {
  let saved: Partial<Connection> = {}
  try {
    saved = JSON.parse(sessionStorage.getItem('shiguang.connection') || '{}')
  } catch {
    /* use defaults */
  }
  const baseUrl = ref(
    typeof saved.baseUrl === 'string' ? saved.baseUrl : defaults.baseUrl,
  )
  const apiKey = ref(typeof saved.apiKey === 'string' ? saved.apiKey : '')
  const userId = ref(
    typeof saved.userId === 'string' && saved.userId
      ? saved.userId
      : defaults.userId,
  )
  const stream = ref(typeof saved.stream === 'boolean' ? saved.stream : true)
  watch([baseUrl, apiKey, userId, stream], () => {
    try {
      sessionStorage.setItem(
        'shiguang.connection',
        JSON.stringify({
          baseUrl: baseUrl.value,
          apiKey: apiKey.value,
          userId: userId.value,
          stream: stream.value,
        }),
      )
    } catch {
      /* storage unavailable */
    }
  })
  return { baseUrl, apiKey, userId, stream }
})
