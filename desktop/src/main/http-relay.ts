import { ipcMain, net } from 'electron'

// 一个小型 HTTP 中继，以便渲染器可以从以下地址访问外部 HTTPS 端点
// 主进程（file:// 渲染器原点否则会被 CORS 阻止）。
// 它故意是通用的，并且不包含特定于产品的知识；任何
// 可选扩展可以使用它。请求限制为 https 以避免
// 成为开放的本地代理。

export interface RelayRequest {
  url: string
  method?: string
  headers?: Record<string, string>
  // 字符串化主体（调用者自己序列化 JSON/表单）。
  body?: string
}

export interface RelayResponse {
  ok: boolean
  status: number
  headers: Record<string, string>
  body: string
}

const MAX_BODY_BYTES = 8 * 1024 * 1024
// 中继调用者都是轻量级 JSON 端点（登录、代码、余额、
// 型号列表）； 10 秒的上限很慷慨，同时仍然可以防止请求停滞
// 免于永远挂起（对于民意调查者来说，会在蜱虫上堆积起来）。
const REQUEST_TIMEOUT_MS = 10 * 1000

function relay(req: RelayRequest): Promise<RelayResponse> {
  return new Promise((resolve, reject) => {
    let parsed: URL
    try {
      parsed = new URL(req.url)
    } catch {
      reject(new Error('invalid url'))
      return
    }
    if (parsed.protocol !== 'https:') {
      reject(new Error('only https is allowed'))
      return
    }

    const request = net.request({
      method: req.method || 'GET',
      url: req.url,
    })
    if (req.headers) {
      for (const [k, v] of Object.entries(req.headers)) request.setHeader(k, v)
    }

    // 限制整个请求（连接+响应），因此停滞的端点无法
    // 永远挂起来。超时时我们中止，这表现为“错误”事件。
    // `done` 防止定时器触发后两次稳定。
    let done = false
    const timer = setTimeout(() => {
      if (done) return
      request.abort()
      reject(new Error('request timeout'))
    }, REQUEST_TIMEOUT_MS)
    const settle = (fn: () => void) => {
      if (done) return
      done = true
      clearTimeout(timer)
      fn()
    }

    request.on('response', (response) => {
      const chunks: Buffer[] = []
      let size = 0
      let aborted = false
      response.on('data', (chunk: Buffer) => {
        if (aborted || done) return
        size += chunk.length
        if (size > MAX_BODY_BYTES) {
          aborted = true
          request.abort()
          settle(() => reject(new Error('response too large')))
          return
        }
        chunks.push(chunk)
      })
      response.on('end', () => {
        if (aborted) return
        const headers: Record<string, string> = {}
        for (const [k, v] of Object.entries(response.headers)) {
          headers[k] = Array.isArray(v) ? v.join(', ') : String(v)
        }
        const status = response.statusCode || 0
        settle(() =>
          resolve({
            ok: status >= 200 && status < 300,
            status,
            headers,
            body: Buffer.concat(chunks).toString('utf8'),
          }),
        )
      })
    })
    request.on('error', (err) => settle(() => reject(err)))

    if (req.body != null) request.write(req.body)
    request.end()
  })
}

export function setupHttpRelayIPC() {
  ipcMain.handle('http-relay', async (_event, req: RelayRequest) => {
    try {
      return await relay(req)
    } catch (e) {
      return { ok: false, status: 0, headers: {}, body: String((e as Error).message) }
    }
  })
}
