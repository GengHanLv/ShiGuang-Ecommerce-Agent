import { beforeEach, describe, expect, it, vi } from 'vitest'
import { exportTaskPdf, fetchDocumentPdf } from './documents'
import { http } from './http'

vi.mock('./http', () => ({
  http: { post: vi.fn(), get: vi.fn() },
  errorMessage: () => '连接失败',
}))
const failure = (data: unknown) => ({
  isAxiosError: true,
  response: { status: 404, data },
})

describe('PDF export requests', () => {
  beforeEach(() => vi.clearAllMocks())
  it('exports through the configured API client and downloads the returned file', async () => {
    const id = 'a'.repeat(64)
    const doc = {
      id,
      title: '咨询记录',
      format: 'pdf',
      download_url: `/documents/${id}/download`,
      created: 1,
    }
    vi.mocked(http.post).mockResolvedValue({ data: { document: doc } })
    const blob = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    vi.mocked(http.get).mockResolvedValue({ data: blob })
    expect(await exportTaskPdf('run-id')).toEqual(doc)
    expect(http.post).toHaveBeenCalledWith(
      '/documents/from-task/run-id',
      {},
      { timeout: 60000 },
    )
    expect(await fetchDocumentPdf(id)).toBe(blob)
    expect(http.get).toHaveBeenCalledWith(`/documents/${id}/download`, {
      responseType: 'blob',
      timeout: 60000,
    })
  })
  it('explains an outdated backend instead of showing raw Not Found', async () => {
    vi.mocked(http.post).mockRejectedValue(failure({ detail: 'Not Found' }))
    await expect(exportTaskPdf('run')).rejects.toThrow(
      '当前后端未加载 PDF 接口',
    )
  })
  it('distinguishes a missing history record from a missing API', async () => {
    vi.mocked(http.post).mockRejectedValue(failure({ detail: '任务不存在' }))
    await expect(exportTaskPdf('run')).rejects.toThrow('服务端任务记录不存在')
  })
  it('decodes JSON errors returned by a blob download', async () => {
    vi.mocked(http.get).mockRejectedValue(
      failure(new Blob([JSON.stringify({ detail: '文件不存在' })])),
    )
    await expect(fetchDocumentPdf('b'.repeat(64))).rejects.toThrow(
      '请重新导出 PDF',
    )
  })
})
