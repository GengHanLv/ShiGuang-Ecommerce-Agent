import { ref, onMounted, watch } from 'vue'
import { checkHealth } from '@/api/workspace'
import { useConnectionStore } from '@/stores/connection'
export function useServiceStatus() {
  const state = ref<'checking' | 'online' | 'offline'>('checking')
  async function refresh() {
    state.value = 'checking'
    try {
      await checkHealth()
      state.value = 'online'
    } catch {
      state.value = 'offline'
    }
  }
  onMounted(refresh)
  watch(() => useConnectionStore().baseUrl, refresh)
  return { state, refresh }
}
