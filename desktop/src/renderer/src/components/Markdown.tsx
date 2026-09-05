import React, { useMemo, useRef, useCallback } from 'react'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { t } from '../i18n'
import apiClient from '../api/client'
import { workspaceHrefOf } from '../lib/fileKind'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useLightboxStore } from './Lightbox'

/**
 * Markdown renderer aligned 1:1 with the web console (markdown-it + highlight.js
 * + GitHub themes). Using the same engine guarantees identical line-break,
 * linkify and code-highlight behavior across web and desktop.
 */

const md: MarkdownIt = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch {
        /* 跌倒 */
      }
    }
    try {
      return hljs.highlightAuto(str).value
    } catch {
      return ''
    }
  },
})

// CommonMark 的侧翼规则对每个 Unicode 标点符号都一视同仁，因此
// `是**"引号"**——` never opens emphasis: the quote after `**` is punctuation
// while 是 before it is neither punctuation nor space, and the run degrades to
// 字面星号。应用中日韩友好修正案
// (github.com/tats-u/markdown-cjk-friend)：与 CJK 邻居一起运行 `*` 并
// 没有相邻的空白同时打开和关闭。 `_` 保留库存规则，
// 其词内行为取决于原始分类。
const _CJK_CHAR =
  /[\u1100-\u11FF\u2E80-\u303F\u3040-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/
const _StateInline = md.inline.State as unknown as {
  prototype: {
    scanDelims(start: number, canSplitWord: boolean): { can_open: boolean; can_close: boolean; length: number }
    src: string
    posMax: number
  }
}
const _scanDelims = _StateInline.prototype.scanDelims
_StateInline.prototype.scanDelims = function (start, canSplitWord) {
  const res = _scanDelims.call(this, start, canSplitWord)
  if (!canSplitWord) return res
  const lastCode = start > 0 ? this.src.charCodeAt(start - 1) : 0x20
  const nextPos = start + res.length
  const nextCode = nextPos < this.posMax ? this.src.charCodeAt(nextPos) : 0x20
  if (md.utils.isWhiteSpace(lastCode) || md.utils.isWhiteSpace(nextCode)) return res
  if (!_CJK_CHAR.test(String.fromCharCode(lastCode)) && !_CJK_CHAR.test(String.fromCharCode(nextCode))) return res
  res.can_open = true
  res.can_close = true
  return res
}

// 修复贪婪的 linkify: markdown - 它的 linkify 吞噬了 markdown 强调 (`*`)
// 和粘贴到 URL 的 CJK 全角标点符号（常见于 LLM 输出，例如
// `**https://x**，中文`), turning the whole tail into one broken link. Cut the
// 第一个此类字符处的 URL 并将其余部分以纯文本形式返回。
const _GREEDY_LINK_CUT = /[*\u3000-\u303F\uFF00-\uFFEF]/
md.core.ruler.after('linkify', 'fix_greedy_linkify', (state) => {
  for (const blk of state.tokens) {
    if (blk.type !== 'inline' || !blk.children) continue
    const ch = blk.children
    for (let i = 0; i < ch.length; i++) {
      const open = ch[i]
      if (open.type !== 'link_open' || open.markup !== 'linkify') continue
      const textTok = ch[i + 1]
      const close = ch[i + 2]
      if (!textTok || textTok.type !== 'text' || !close || close.type !== 'link_close') continue
      const idx = textTok.content.search(_GREEDY_LINK_CUT)
      if (idx < 0) continue
      const keep = textTok.content.slice(0, idx)
      const spill = textTok.content.slice(idx)
      textTok.content = keep
      open.attrSet('href', keep)
      const spillTok = new state.Token('text', '', 0)
      spillTok.content = spill
      ch.splice(i + 3, 0, spillTok)
    }
  }
})

// 安全地在新选项卡中打开链接。
const defaultLinkOpen =
  md.renderer.rules.link_open ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  // 工作区相关的 href 在应用程序之外没有任何意义：`target=_blank`
  // 会将其交给操作系统浏览器，操作系统浏览器根据渲染器的解析来解析它
  // 文件:// URL。对其进行标记，以便单击处理程序打开预览面板。
  const wsPath = workspaceHrefOf(token.attrGet('href') || '')
  if (wsPath) {
    token.attrPush(['data-ws-path', wsPath])
    token.attrJoin('class', 'ws-link')
  } else {
    token.attrPush(['target', '_blank'])
    token.attrPush(['rel', 'noopener noreferrer'])
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// 代理生成的图像由其本地路径引用 (`/Users/.../x.png`
// 或`~/...`）。渲染器从 file:// 或开发服务器运行，所以这样的 src
// 永远不会自行解析 - 通过后端文件端点路由它，这
// 采用绝对路径并强制使用允许的根。
const defaultImage =
  md.renderer.rules.image ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.image = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  const src = token.attrGet('src') || ''
  const baseDir = (env as { imageBaseDir?: string } | undefined)?.imageBaseDir
  if (/^~\//.test(src) || src.startsWith('/')) {
    token.attrSet('src', apiClient.getServeFileUrl(src))
  } else if (baseDir && !/^[a-zA-Z][\w+.-]*:/.test(src)) {
    // 文档相关图像（例如知识降价`../images/x.png`）：解决
    // 针对文档的目录（通过渲染环境传递）并通过 /api/file 提供服务。
    let rel = src
    try {
      rel = decodeURIComponent(rel)
    } catch {
      /* 保持原始形式 */
    }
    const combined = `${baseDir}/${rel.split('?')[0]}`
    const segments: string[] = []
    for (const seg of combined.split('/')) {
      if (seg === '..') segments.pop()
      else if (seg !== '.' && seg !== '') segments.push(seg)
    }
    // Unix baseDir 是绝对的，因此恢复前导斜杠 split() 删除的内容
    // （像 C:/x 这样的 Windows 驱动器路径保留其自己的前缀）。 /api/文件拒绝
    // 非绝对路径。
    const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/')
    token.attrSet('src', apiClient.getServeFileUrl(resolved))
  }
  return defaultImage(tokens, idx, options, env, self)
}

// 表格不能缩小到低于其列的最小内容宽度，因此宽
// 比较表将超越泡沫。将其包裹在滚动条中：表格
// 当气泡适合时，会继续填充气泡；当气泡不适合时，会向侧面滚动。
const defaultTableOpen =
  md.renderer.rules.table_open ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
const defaultTableClose =
  md.renderer.rules.table_close ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.table_open = function (tokens, idx, options, env, self) {
  return `<div class="table-wrap">` + defaultTableOpen(tokens, idx, options, env, self)
}
md.renderer.rules.table_close = function (tokens, idx, options, env, self) {
  return defaultTableClose(tokens, idx, options, env, self) + `</div>`
}

// 包装受保护的代码块，以便我们可以渲染标题（lang + 复制按钮）。
const defaultFence =
  md.renderer.rules.fence ||
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }
md.renderer.rules.fence = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  const info = token.info ? token.info.trim().split(/\s+/)[0] : ''
  // 确保 `hljs` 类存在，以便 GitHub 主题背景/基础
  // 颜色适用（markdown - 默认情况下仅添加语言 - *）。
  let rendered = defaultFence(tokens, idx, options, env, self)
  if (rendered.includes('<code class="')) {
    rendered = rendered.replace('<code class="', '<code class="hljs ')
  } else {
    rendered = rendered.replace('<code>', '<code class="hljs">')
  }
  return (
    `<div class="code-block-wrapper">` +
    `<div class="code-block-header">` +
    `<span class="code-block-lang">${info || 'text'}</span>` +
    `<button type="button" class="code-copy-btn" data-code-id="cb-${idx}" aria-label="Copy code">${t('msg_copy')}</button>` +
    `</div>` +
    rendered +
    `</div>`
  )
}

interface MarkdownProps {
  content: string
  /**
   * Intercept clicks on internal document links (relative `.md` hrefs). When
   * provided, such links open in-app instead of being handed to the OS. Used by
   * the knowledge viewer so index links open the target doc rather than firing
   * an "application cannot be opened (-120)" error in Electron.
   */
  onInternalLink?: (href: string) => void
  /**
   * Absolute directory of the document the markdown comes from, so image srcs
   * that are relative to it (`../images/x.png`) resolve to real files. Used by
   * the knowledge viewer; without it relative srcs are left untouched.
   */
  imageBaseDir?: string
}

const Markdown: React.FC<MarkdownProps> = ({ content, onInternalLink, imageBaseDir }) => {
  const rootRef = useRef<HTMLDivElement>(null)

  const html = useMemo(() => md.render(content || '', { imageBaseDir }), [content, imageBaseDir])

  // 委托点击：图像缩放、代码块上的复制按钮、内部文档链接。
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement

      // 任何内嵌图像都会在灯箱中打开。
      const img = target.closest('img') as HTMLImageElement | null
      if (img) {
        useLightboxStore.getState().open(img.currentSrc || img.src)
        return
      }

      // 当提供处理程序时，内部知识链接（相对 *.md）。
      if (onInternalLink) {
        const a = target.closest('a') as HTMLAnchorElement | null
        if (a) {
          const href = a.getAttribute('href') || ''
          if (href.endsWith('.md') && !/^https?:\/\//i.test(href)) {
            e.preventDefault()
            onInternalLink(href)
            return
          }
        }
      }

      // 工作区文件的链接在预览面板中打开。
      const wsLink = target.closest('a[data-ws-path]') as HTMLAnchorElement | null
      if (wsLink) {
        e.preventDefault()
        useWorkspaceStore.getState().openLink(wsLink.dataset.wsPath || '')
        return
      }

      const btn = target.closest('.code-copy-btn') as HTMLElement | null
      if (!btn) return
      const pre = btn.closest('.code-block-wrapper')?.querySelector('pre')
      if (!pre) return
      navigator.clipboard.writeText(pre.textContent || '')
      const original = btn.textContent
      btn.textContent = t('msg_copied')
      btn.classList.add('copied')
      setTimeout(() => {
        btn.textContent = original
        btn.classList.remove('copied')
      }, 1600)
    },
    [onInternalLink]
  )

  return (
    <div
      ref={rootRef}
      className="msg-content text-sm text-content leading-relaxed break-words"
      onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default Markdown
