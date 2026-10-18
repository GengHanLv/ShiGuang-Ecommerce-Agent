import { http } from './http'
import type { KnowledgeCollection, ServiceStatus, UploadResult } from '@/types'
export async function checkHealth() {
  return (await http.get<{ status: string }>('/health', { timeout: 5000 })).data
}
export async function checkServices() {
  return (await http.get<ServiceStatus>('/status', { timeout: 15000 })).data
}
export async function getKnowledge() {
  return (await http.get<{ collections: KnowledgeCollection[] }>('/knowledge'))
    .data.collections
}
export async function uploadKnowledge(
  file: File,
  collection: string,
  onProgress: (progress: number) => void,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('collection', collection)
  return (
    await http.post<UploadResult>('/upload', form, {
      timeout: 300000,
      onUploadProgress: (progress) =>
        onProgress(
          Math.round((progress.loaded / (progress.total || file.size)) * 100),
        ),
    })
  ).data
}
