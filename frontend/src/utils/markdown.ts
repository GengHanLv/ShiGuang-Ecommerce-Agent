import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
markdown.linkify.set({ fuzzyEmail: false, fuzzyLink: false })
// 仅允许显式 HTTP(S) 链接；HTML 与模型自行生成的图片始终不执行。
markdown.validateLink = (value: string) => {
  try {
    const url = new URL(value)
    return (
      ['https:', 'http:'].includes(url.protocol) &&
      // 避免自动识别器把带认证信息的无效 URL 截成 https://user。
      (url.hostname.includes('.') || url.hostname === 'localhost') &&
      !url.username &&
      !url.password &&
      !value.includes('\\')
    )
  } catch {
    return false
  }
}
markdown.renderer.rules.image = (tokens, index) =>
  markdown.utils.escapeHtml(tokens[index]!.content)
markdown.renderer.rules.link_open = (tokens, index, options, _env, self) => {
  const token = tokens[index]!
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  token.attrSet('referrerpolicy', 'no-referrer')
  return self.renderToken(tokens, index, options)
}
export function renderMarkdown(content: string) {
  return markdown.render(content)
}
