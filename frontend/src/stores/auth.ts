import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { http } from '@/api/http'
export interface AuthUser {
  id: string
  username: string
  role: 'admin' | 'user'
}
export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const ready = ref(false)
  const admin = computed(() => user.value?.role === 'admin')
  async function refresh() {
    try {
      user.value = (await http.get<AuthUser>('/auth/me')).data
    } catch {
      user.value = null
    } finally {
      ready.value = true
    }
  }
  async function login(username: string, password: string) {
    user.value = (
      await http.post<AuthUser>('/auth/login', { username, password })
    ).data
    ready.value = true
  }
  async function register(username: string, password: string) {
    await http.post('/auth/register', { username, password })
    await login(username, password)
  }
  async function logout() {
    try {
      await http.post('/auth/logout')
    } finally {
      user.value = null
    }
  }
  window.addEventListener('auth-expired', () => {
    user.value = null
  })
  return { user, ready, admin, refresh, login, register, logout }
})
