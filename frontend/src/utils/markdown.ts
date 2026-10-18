import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: false })
// Keep display local: model output cannot load images or introduce navigation.
markdown.renderer.rules.image = (tokens, index) =>
  markdown.utils.escapeHtml(tokens[index]!.content)
markdown.renderer.rules.link_open = () => ''
markdown.renderer.rules.link_close = () => ''
export function renderMarkdown(content: string) {
  return markdown.render(content)
}
