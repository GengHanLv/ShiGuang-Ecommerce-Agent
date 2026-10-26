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
  it('renders named sources and plain HTTPS URLs as safe new-tab links', () => {
    const result = renderMarkdown(
      '[官网规格](https://example.com/specs?q=1&v=2)\nhttps://example.com/help',
    )
    expect(result).toContain('href="https://example.com/specs?q=1&amp;v=2"')
    expect(result).toContain('target="_blank"')
    expect(result).toContain('rel="noopener noreferrer"')
    expect(result).toContain('>官网规格</a>')
    expect(result).toContain('href="https://example.com/help"')
  })
  it.each([
    'javascript:alert(1)',
    'data:text/html;base64,AAAA',
    'file:///C:/private',
    '//example.com',
    'https://user:pass@example.com',
  ])('does not activate unsafe URL %s', (url) => {
    expect(renderMarkdown(`[查看](${url})`)).not.toContain('<a ')
  })
  it('escapes HTML attributes and does not create links for document filenames', () => {
    expect(
      renderMarkdown('[官网](https://example.com "\" onclick=\"alert(1)")'),
    ).not.toContain(' onclick="')
    expect(
      renderMarkdown('说明.pdf；README.md；user@example.com'),
    ).not.toContain('<a ')
  })
})
