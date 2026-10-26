import axios from 'axios'
import { http, errorMessage } from './http'
import type { SavedDocument } from '@/types'

async function documentError(error: unknown, operation: 'export' | 'download') {
  if (axios.isAxiosError(error)) {
    let data = error.response?.data
    if (data instanceof Blob) {
      try {
        data = JSON.parse(await data.text())
      } catch {
        /* non-JSON response */
      }
    }
    if (error.response?.status === 404) {
      if (data?.detail === 'Not Found')
        return new Error('当前后端未加载 PDF 接口，请重启本项目后端后再试')
      return new Error(
        operation === 'export'
          ? '该历史消息的服务端任务记录不存在，无法导出 PDF'
          : '文件不存在或已失效，请重新导出 PDF',
      )
    }
    if (typeof data?.detail === 'string') return new Error(data.detail)
  }
  return new Error(errorMessage(error))
}

export async function exportTaskPdf(runId: string): Promise<SavedDocument> {
  try {
    const result = await http.post<{ document: SavedDocument }>(
      `/documents/from-task/${encodeURIComponent(runId)}`,
      {},
      { timeout: 60000 },
    )
    return result.data.document
  } catch (error) {
    throw await documentError(error, 'export')
  }
}

export async function fetchDocumentPdf(id: string): Promise<Blob> {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error('文件标识无效')
  try {
    const result = await http.get<Blob>(`/documents/${id}/download`, {
      responseType: 'blob',
      timeout: 60000,
    })
    return result.data
  } catch (error) {
    throw await documentError(error, 'download')
  }
}
