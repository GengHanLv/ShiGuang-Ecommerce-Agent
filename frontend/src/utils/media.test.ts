import { describe, expect, it } from 'vitest'
import { safeProductImages, productImageUrl } from './media'

const image = {
  model: '测试型号',
  alt: '官网产品图',
  url: '/media/' + 'a'.repeat(64),
  source_url: 'https://consumer.huawei.com/cn/product/',
}
describe('product image cards', () => {
  it('accepts verified official domains and limits the gallery size', () => {
    expect(safeProductImages([image])).toEqual([image])
    expect(productImageUrl(image.url)).toBe('/api' + image.url)
    expect(safeProductImages(Array(5).fill(image))).toHaveLength(3)
  })
  it('rejects malformed history, injected images and deceptive hosts', () => {
    expect(safeProductImages(null)).toEqual([])
    expect(
      safeProductImages([
        null,
        {},
        {
          ...image,
          url: 'https://consumer.huawei.com.evil.example/product.jpg',
        },
        { ...image, source_url: 'javascript:alert(1)' },
        { ...image, url: 'data:image/svg+xml;base64,AAAA' },
        { ...image, url: 'https://user:pass@consumer.huawei.com/product.jpg' },
      ]),
    ).toEqual([])
  })
})
