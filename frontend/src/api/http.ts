import axios from 'axios'
import { useConnectionStore } from '@/stores/connection'
export const http = axios.create({ timeout: 20000 })
http.interceptors.request.use((config) => {
  const settings = useConnectionStore()
  config.baseURL = settings.baseUrl.replace(/\/$/, '')
  if (settings.apiKey) config.headers.set('X-API-Key', settings.apiKey)
  return config
})
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.code === 'ERR_CANCELED') return '已停止生成'
    if (error.response?.status === 401)
      return '连接凭证无效，请在连接设置中填写正确的 API Key'
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (error.response?.status === 422) return '请求内容格式不正确，请检查输入'
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT')
      return '请求超时，请稍后再试'
    return '暂时无法连接服务，请检查后端地址与运行状态'
  }
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}
