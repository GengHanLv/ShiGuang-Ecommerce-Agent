import { defineStore } from 'pinia'
import { ref, watch, computed } from 'vue'
import { useAuthStore } from './auth'
export const useConnectionStore = defineStore('connection', () => {
  const auth = useAuthStore()
  let saved: { baseUrl?: string; stream?: boolean } = {}
  try {
    saved = JSON.parse(sessionStorage.getItem('shiguang.connection') || '{}')
  } catch {
    /* defaults */
  }
  const baseUrl = ref(
    typeof saved.baseUrl === 'string'
      ? saved.baseUrl
      : import.meta.env.VITE_API_BASE_URL || '/api',
  )
  const stream = ref(typeof saved.stream === 'boolean' ? saved.stream : true)
  // 登录身份只来自服务端，连接设置不能编辑用户ID；旧API Key不会继续保留。
  const userId = computed(() => auth.user?.id || '')
  function save() {
    sessionStorage.setItem(
      'shiguang.connection',
      JSON.stringify({ baseUrl: baseUrl.value, stream: stream.value }),
    )
  }
  try {
    save()
  } catch {
    /* storage disabled */
  }
  watch([baseUrl, stream], () => {
    try {
      save()
    } catch {
      /* storage disabled */
    }
  })
  return { baseUrl, stream, userId }
})
