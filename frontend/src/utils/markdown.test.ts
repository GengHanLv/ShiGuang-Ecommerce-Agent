import { describe, it, expect } from 'vitest'
import { renderMarkdown } from './markdown'
describe('assistant formatting', () => {
  it('renders emphasis and lists', () => {
    expect(renderMarkdown('**已发货**')).toContain('<strong>已发货</strong>')
    expect(renderMarkdown('- 一个问题')).toContain('<li>一个问题</li>')
  })
  it('does not execute raw HTML or load external images', () => {
    const result = renderMarkdown(
      '<script>alert(1)</script>\n![image](https://example.com/pixel)',
    )
    expect(result).not.toContain('<script>')
    expect(result).not.toContain('<img')
  })
  it('does not turn generated links into navigation', () => {
    expect(renderMarkdown('[link](https://example.com)')).not.toContain('<a ')
  })
})
