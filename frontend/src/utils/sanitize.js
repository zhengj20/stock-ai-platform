/**
 * HTML 安全清理工具 - 防止 LLM 输出恶意内容导致 XSS
 * 使用 DOMPurify 进行白名单过滤，比正则替换更安全
 */
import DOMPurify from 'dompurify'

// 允许的标签白名单（Markdown 常见元素）
const ALLOWED_TAGS = [
  // 结构
  'div', 'span', 'p', 'br', 'hr', 'blockquote', 'pre', 'code',
  // 标题
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  // 列表
  'ul', 'ol', 'li',
  // 表格
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  // 文本格式
  'strong', 'b', 'em', 'i', 'u', 's', 'del', 'mark', 'sub', 'sup',
  // 链接/图片（受控）
  'a', 'img',
]

// DOMPurify 配置
const PURIFY_CONFIG = {
  ALLOWED_TAGS,
  ADD_ATTRS: ['href', 'src', 'alt', 'title', 'target', 'rel', 'class'],
  ALLOW_DATA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  // 只允许 http/https/mailto 协议
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):)/i,
}

/**
 * 清理 HTML，防止 XSS 攻击
 * @param {string} html - 可能包含恶意内容的 HTML
 * @returns {string} 安全的 HTML
 */
export function sanitizeHtml(html) {
  if (!html || typeof html !== 'string') return ''
  // 浏览器环境使用 DOMPurify，SSR 环境回退到空字符串
  if (typeof window === 'undefined') return ''
  return DOMPurify.sanitize(html, PURIFY_CONFIG)
}

/**
 * Markdown -> 安全 HTML（marked + DOMPurify）
 * @param {string} text - Markdown 文本
 * @returns {string} 安全的 HTML
 */

// 预加载 marked 模块（避免每次调用都动态 import）
let _markedPromise = null
function getMarked() {
  if (!_markedPromise) {
    _markedPromise = import('marked').then(m => {
      m.marked.setOptions({ breaks: true, gfm: true })
      return m.marked
    })
  }
  return _markedPromise
}

export async function renderMarkdown(text) {
  if (!text || typeof text !== 'string') return ''
  try {
    const marked = await getMarked()
    const rawHtml = marked.parse(text)
    return sanitizeHtml(rawHtml)
  } catch (e) {
    console.warn('[Markdown] Parse error:', e)
    return `<pre style="white-space:pre-wrap;">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`
  }
}

export async function renderMarkdownAsync(text) {
  if (!text || typeof text !== 'string') return ''
  try {
    const marked = await getMarked()
    const rawHtml = await marked.parse(text)
    return sanitizeHtml(rawHtml)
  } catch (e) {
    console.warn('[Markdown] Async parse error:', e)
    return `<pre style="white-space:pre-wrap;">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`
  }
}

export default { sanitizeHtml, renderMarkdown, renderMarkdownAsync }
