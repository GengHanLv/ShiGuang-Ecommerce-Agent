import type { ProductImage } from '@/types'
function sourceUrl(value: unknown) {
  if (typeof value !== 'string') return false
  try {
    const url = new URL(value)
    return (
      ['http:', 'https:'].includes(url.protocol) &&
      !url.username &&
      !url.password
    )
  } catch {
    return false
  }
}
// 配图只能来自后端已登记的联网资产，不能让模型或浏览器历史拼任意远程图片。
export function safeProductImages(value: unknown): ProductImage[] {
  if (!Array.isArray(value)) return []
  return value
    .filter(
      (item): item is ProductImage =>
        item &&
        typeof item === 'object' &&
        typeof item.model === 'string' &&
        typeof item.alt === 'string' &&
        /^\/media\/[a-f0-9]{64}$/.test(item.url) &&
        sourceUrl(item.source_url),
    )
    .slice(0, 3)
}
export function productImageUrl(path: string, baseUrl = '/api') {
  return `${baseUrl.replace(/\/$/, '')}${path}`
}
