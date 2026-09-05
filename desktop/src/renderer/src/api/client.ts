import type {
  ConfigData,
  ChannelInfo,
  ChannelAction,
  SkillInfo,
  SkillContent,
  ToolInfo,
  MemoryItem,
  MemoryCategory,
  MemoryPage,
  MemoryDoc,
  SchedulerTask,
  Attachment,
  SessionsPage,
  SessionSettingsState,
  HistoryPage,
  ModelsData,
  ModelsAction,
  KnowledgeList,
  KnowledgeGraph,
  KnowledgeAction,
  KnowledgeImportPayload,
  WorkspaceEntry,
  WorkspaceReadResult,
  WorkspaceTree,
  WorkspaceWriteResult,
  ProjectState,
  ChannelsResponse,
  RosterSnapshot,
} from '../types'
import { getLang } from '../i18n'

export interface ApiResult {
  status: string
  message?: string
}

const AUTH_TOKEN_KEY = 'cow_auth_token'

class ApiClient {
  private baseUrl = 'http://127.0.0.1:9876'
  // 用于受 web_password 保护的后端的不记名令牌。桌面渲染器
  // 从 file:// 原点运行，其中跨域 cookie 为 http://127.0.0.1
  // 发送不可靠，因此我们通过授权标头进行身份验证
  // 相反。保留在 localStorage 中，因此可以在重新加载后继续存在。
  private authToken: string | null =
    typeof localStorage !== 'undefined' ? localStorage.getItem(AUTH_TOKEN_KEY) : null

  setBaseUrl(url: string) {
    this.baseUrl = url
  }

  getBaseUrl() {
    return this.baseUrl
  }

  setAuthToken(token: string | null) {
    this.authToken = token
    try {
      if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
      else localStorage.removeItem(AUTH_TOKEN_KEY)
    } catch {
      // localStorage可能不可用；内存中令牌在本次会话中仍然有效
    }
  }

  // 工作区范围端点（技能/知识/调度程序，
  // 和新的聊天会话）应该瞄准。空的意思是“让后端使用它的
  // 默认代理” — 正是传统的单代理行为，所以没有什么
  // 已发送，旧请求逐字节不变。由代理设置
  // 仅当安装处于多代理模式时才存储。
  private activeAgentId = ''

  setActiveAgentId(id: string) {
    this.activeAgentId = (id || '').trim()
  }

  getActiveAgentId(): string {
    return this.activeAgentId
  }

  // 将 agent_id 附加到查询字符串。显式 `override` 获胜（由
  // 知识/内存页面，其范围为选定的代理，独立于
  // 聊天处于活动状态）；否则使用活性代理。无操作输入
  // 没有覆盖的单代理模式，因此旧版 URL 不会受到影响。
  private scoped(path: string, override?: string): string {
    const id = (override ?? this.activeAgentId) || ''
    if (!id) return path
    const sep = path.includes('?') ? '&' : '?'
    return `${path}${sep}agent_id=${encodeURIComponent(id)}`
  }

  // 设置活动代理时，将 agent_id 添加到 JSON 正文，而不会破坏
  // 调用者已将显式的 agent_id 放在那里。单代理模式下无操作。
  private withAgent<T extends Record<string, unknown>>(body: T): T {
    if (!this.activeAgentId || 'agent_id' in body) return body
    return { ...body, agent_id: this.activeAgentId }
  }

  // 通过每个请求携带活动代理，就像 Web 控制台的方式一样
  // fetch 包装器的作用：会话、历史、项目、技能、知识和
  // 上传全部存储在每个代理工作区中，因此忘记了的请求
  // id 默默地登陆默认代理的数据。始终查询字符串； JSON
  // 机构也是如此（处理程序读取其中之一）。显式的 agent_id — 甚至是空的
  // 一个 — 总是获胜，因此呼叫者仍然可以联系另一个代理或选择退出
  // （例如聚合调度程序列表）。单Agent模式下无操作，保持
  // 传统请求逐字节不变。
  private carryAgent(path: string, options?: RequestInit): { path: string; options?: RequestInit } {
    const id = this.activeAgentId
    if (!id) return { path, options }
    let url = path
    if (!/[?&]agent_id=/.test(url)) {
      url += `${url.includes('?') ? '&' : '?'}agent_id=${encodeURIComponent(id)}`
    }
    let opts = options
    if (options && typeof options.body === 'string') {
      try {
        const body = JSON.parse(options.body)
        if (body && typeof body === 'object' && !Array.isArray(body) && !('agent_id' in body)) {
          opts = { ...options, body: JSON.stringify({ ...body, agent_id: id }) }
        }
      } catch {
        /* 不是 JSON；留下身体 */
      }
    }
    return { path: url, options: opts }
  }

  private async request<T>(path: string, rawOptions?: RequestInit): Promise<T> {
    const { path: url, options } = this.carryAgent(path, rawOptions)
    const res = await fetch(`${this.baseUrl}${url}`, {
      ...options,
      // Cookie 仍然适用于浏览器访问；桌面应用程序依赖于
      // 下面的授权标头。
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {}),
        ...options?.headers,
      },
    })
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }
    return res.json()
  }

  /** POST multipart form data.
   *
   * `request()` can't be reused: it forces a JSON content type, while FormData
   * must set its own multipart boundary. The auth header still has to be wired
   * up by hand — the desktop app renders from file://, so it authenticates via
   * the header, never the cookie.
   */
  private async postFormData<T>(path: string, formData: FormData): Promise<T> {
    // 当查询已经完成时，多部分主体不得获取 agent_id 的副本
    // 携带它：web.py 合并查询+表单字段并且重复折叠
    // 到一个列表中，这会破坏需要字符串的处理程序。所以范围通过
    // 仅查询，并且仅当表单尚未命名代理时。
    const scopedPath = formData.has('agent_id') ? path : this.carryAgent(path).path
    const url = `${this.baseUrl}${scopedPath}`
    // 永远不会到达后端的普通 `fetch` 会抛出裸露的
    // `TypeError: Failed to fetch`，这在错误报告中没有用。最
    // 这里的常见原因是暂时连接拒绝（本地后端
    // 仍在启动，或短暂重新启动），因此在短暂延迟后重试一次
    // 并且，在持续发生网络故障时，提出一条可操作的消息：
    // 命名目标 URL 而不是不透明的浏览器错误。
    let lastErr: unknown
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 600))
      try {
        const res = await fetch(url, {
          method: 'POST',
          body: formData,
          credentials: 'include',
          headers: this.authToken ? { Authorization: `Bearer ${this.authToken}` } : undefined,
        })
        if (!res.ok) {
          // 即使失败，后端也会返回 JSON 错误；传达其信息
          // 当存在时，用户可以看到真正的原因（例如文件太大）。
          let detail = res.statusText
          try {
            const body = await res.clone().json()
            if (body?.message) detail = body.message
          } catch {
            /* 非 JSON 错误主体 */
          }
          throw new Error(`HTTP ${res.status}: ${detail}`)
        }
        return res.json()
      } catch (e) {
        lastErr = e
        // 仅重试网络级故障；真正的 HTTP 错误是最终的。
        const isNetwork = e instanceof TypeError
        if (!isNetwork) throw e
      }
    }
    console.error(`[api] upload network failure to ${url}:`, lastErr)
    throw new Error(
      `无法连接到本地服务 (${url})，请确认客户端后台正在运行后重试`,
    )
  }

  // ---------------------------------------------------------
  // 聊天/消息
  // ---------------------------------------------------------

  async sendMessage(
    sessionId: string,
    message: string,
    opts?: {
      stream?: boolean
      attachments?: Attachment[]
      isVoice?: boolean
      lang?: string
      /** The conversation's owner Agent; defaults to the active one. */
      agentId?: string
      /** A teammate addressed for this turn (group chat); the owner still owns
       *  the conversation, this only changes who answers. */
      speakerAgentId?: string
    }
  ): Promise<{ status: string; request_id: string; stream: boolean; inline_reply?: string; speaker?: string }> {
    // 当询问时路由到特定代理，否则路由到活动代理。空（遗留
    // single-Agent）完全省略agent_id，因此后端使用其默认值。
    const agentId = opts?.agentId || this.activeAgentId
    const body: Record<string, unknown> = {
      session_id: sessionId,
      message,
      stream: opts?.stream ?? true,
      attachments: opts?.attachments,
      is_voice: opts?.isVoice ?? false,
      lang: opts?.lang,
    }
    if (agentId) body.agent_id = agentId
    if (opts?.speakerAgentId) body.speaker_agent_id = opts.speakerAgentId
    return this.request('/message', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async poll(sessionId: string): Promise<{
    status: string
    has_content: boolean
    content?: string
    request_id?: string
    timestamp?: number
  }> {
    return this.request('/poll', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    })
  }

  async cancel(opts: { requestId?: string; sessionId?: string; lang?: string }): Promise<{ status: string; cancelled: number }> {
    return this.request('/cancel', {
      method: 'POST',
      body: JSON.stringify({ request_id: opts.requestId, session_id: opts.sessionId, lang: opts.lang }),
    })
  }

  // EventSource 无法设置授权标头，因此将身份验证令牌附加为
  // SSE 端点的查询参数（后端在那里接受它）。
  private withToken(url: string): string {
    if (!this.authToken) return url
    const sep = url.includes('?') ? '&' : '?'
    return `${url}${sep}token=${encodeURIComponent(this.authToken)}`
  }

  createSSEStream(requestId: string): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/stream?request_id=${requestId}`))
  }

  async deleteMessage(opts: {
    sessionId: string
    userSeq: number
    deleteUser?: boolean
    cascade?: boolean
    /** Owner of the session; defaults to the active Agent. */
    agentId?: string
  }): Promise<{ status: string; deleted: number }> {
    const body: Record<string, unknown> = {
      session_id: opts.sessionId,
      user_seq: opts.userSeq,
      delete_user: opts.deleteUser ?? true,
      cascade: opts.cascade ?? false,
    }
    if (opts.agentId) body.agent_id = opts.agentId
    return this.request('/api/messages/delete', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------
  // 上传/文件
  // ---------------------------------------------------------

  async uploadFile(file: File, sessionId?: string): Promise<{
    status: string
    file_path: string
    file_name: string
    file_type: string
    preview_url: string
    message?: string
  }> {
    const formData = new FormData()
    // 将文件读入内存（Blob），而不是直接追加文件。
    // 在 Electron 中，`fetch` 间歇性地直接从磁盘传输文件
    // 拒绝并显示“无法获取”（net::ERR whileReading the backing）
    // 文件 - 移动/锁定路径、沙箱、名称中的特殊字符），甚至对于
    // 小文件。首先物化字节避开了磁盘流
    // 路径；原始名称被保留，因此后端保留扩展名。
    try {
      const buf = await file.arrayBuffer()
      formData.append('file', new Blob([buf], { type: file.type }), file.name)
    } catch {
      // 读取失败（罕见）：回退到原始文件，因此行为会降低
      // 优雅地而不是完全阻止上传。
      formData.append('file', file)
    }
    if (sessionId) formData.append('session_id', sessionId)
    return this.postFormData('/upload', formData)
  }

  getFileUrl(previewUrl: string): string {
    if (/^https?:\/\//.test(previewUrl)) return previewUrl
    // 通过 <img src> 提供服务，它无法设置标头 - 在
    // 查询在 web_password 下加载的受保护文件端点。
    return this.withToken(`${this.baseUrl}${previewUrl}`)
  }

  getServeFileUrl(absPath: string): string {
    return this.withToken(`${this.baseUrl}/api/file?path=${encodeURIComponent(absPath)}`)
  }

  // ---------------------------------------------------------
  // 工作区浏览/预览
  // ---------------------------------------------------------

  // 工作区端点接受可选会话，以便它们根据
  // 会话的项目目录（当一个打开时）而不是始终〜/cow。
  private sessionQuery(session?: string): string {
    return session ? `&session=${encodeURIComponent(session)}` : ''
  }

  async workspaceTree(path = '', session?: string): Promise<WorkspaceTree & ApiResult> {
    return this.request(`/api/workspace/tree?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  async workspaceSearch(query: string, limit = 30, session?: string): Promise<{ results: WorkspaceEntry[] } & ApiResult> {
    return this.request(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=${limit}${this.sessionQuery(session)}`)
  }

  async workspaceResolve(path: string, session?: string): Promise<{ file: WorkspaceEntry } & ApiResult> {
    return this.request(`/api/workspace/resolve?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  /**
   * Text content of one workspace file, for the preview panel's editor.
   *
   * Unlike the preview URL used for rendering, this reports the `mtime` to pass
   * back on save and whether the file is editable at all.
   */
  async workspaceRead(path: string, session?: string): Promise<WorkspaceReadResult & ApiResult> {
    return this.request(`/api/workspace/read?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  /**
   * Save edited text back to a workspace file.
   *
   * The backend answers 200 even when it refuses, so the caller must check
   * `status`: `code === 'conflict'` means the file changed since
   * `expectedMtime` and the user has to choose between reloading and
   * overwriting. Pass `expectedMtime: null` to force the overwrite.
   */
  async workspaceWrite(args: {
    path: string
    content: string
    session?: string
    expectedMtime?: number | null
  }): Promise<WorkspaceWriteResult & ApiResult> {
    return this.request('/api/workspace/write', {
      method: 'POST',
      body: JSON.stringify({
        path: args.path,
        content: args.content,
        session: args.session || '',
        expected_mtime: args.expectedMtime ?? null,
      }),
    })
  }

  // ---------------------------------------------------------
  // 项目工作区（每个会话工作目录）
  // ---------------------------------------------------------

  async getProjects(session: string): Promise<ProjectState & ApiResult> {
    return this.request(`/api/projects?session=${encodeURIComponent(session)}`)
  }

  /** Bind the session to a project dir, or clear it (projectDir=null → ~/cow). */
  async selectProject(session: string, projectDir: string | null): Promise<ProjectState & ApiResult> {
    return this.request('/api/projects/select', {
      method: 'POST',
      body: JSON.stringify({ session, project_dir: projectDir }),
    })
  }

  /** Create a new project folder under the projects root and select it. */
  async createProject(session: string, name: string): Promise<ProjectState & ApiResult & { path?: string }> {
    return this.request('/api/projects/create', {
      method: 'POST',
      body: JSON.stringify({ session, name }),
    })
  }

  /** Persist the user-defined order of project spaces in the sidebar. */
  async setProjectsOrder(order: string[]): Promise<ApiResult> {
    return this.request('/api/projects/order', {
      method: 'POST',
      body: JSON.stringify({ order }),
    })
  }

  /** Rename a project's display label (record only; files on disk untouched). */
  async renameProject(path: string, name: string): Promise<ApiResult & { name?: string }> {
    return this.request('/api/projects/manage', {
      method: 'PUT',
      body: JSON.stringify({ path, name }),
    })
  }

  /** Forget a project record and unbind its sessions (files on disk kept). */
  async deleteProject(path: string): Promise<ApiResult & { unbound?: number }> {
    return this.request('/api/projects/manage', {
      method: 'DELETE',
      body: JSON.stringify({ path }),
    })
  }

  /** Absolute URL for a `/preview/...` path. The signed token in the path is
   *  what authorizes it, so no auth token is appended. */
  getPreviewUrl(previewPath: string): string {
    if (/^https?:\/\//.test(previewPath)) return previewPath
    return `${this.baseUrl}${previewPath}`
  }

  // ---------------------------------------------------------
  // 会议
  // ---------------------------------------------------------

  // 对话发生在其所有者特工的商店中。下面的每个会话调用
  // 显式获取所有者 (`agentId`) 以便列表可以作用于任何行，而不是
  // 只是活跃代理的；当省略时，活动代理（该代理的所有者）
  // 开放式对话）是自动进行的。单代理安装通行证
  // 什么都没有并得到遗留请求。

  /** All Agents' web sessions merged into one recency-ordered list. A
   *  single-Agent backend returns exactly its own list (with an `agent` badge);
   *  a legacy backend ignores the unknown `scope` parameter. */
  async getSessions(page = 1, pageSize = 50): Promise<SessionsPage> {
    return this.request<{ status: string } & SessionsPage>(
      `/api/sessions?page=${page}&page_size=${pageSize}&scope=all`
    )
  }

  async deleteSession(sessionId: string, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'DELETE',
    })
  }

  async renameSession(sessionId: string, title: string, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'PUT',
      body: JSON.stringify(agentId ? { title, agent_id: agentId } : { title }),
    })
  }

  /** Pin or unpin a session; pinned sessions sort to the top of their group. */
  async setSessionPinned(sessionId: string, pinned: boolean, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'PUT',
      body: JSON.stringify(agentId ? { pinned, agent_id: agentId } : { pinned }),
    })
  }

  /** This session's effective model + permission (and team), with the catalog to switch. */
  async getSessionSettings(sessionId: string, agentId?: string): Promise<{ status: string } & SessionSettingsState> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, agentId))
  }

  /** Set or clear this session's model / permission override, or its team
   *  members. Pass null to a field to drop the override and follow the global
   *  default (null members = nobody invited). */
  async updateSessionSettings(
    sessionId: string,
    body: { provider?: string | null; model?: string | null; permission?: string | null; members?: string[] | null },
    agentId?: string
  ): Promise<{ status: string } & Partial<SessionSettingsState> & { message?: string }> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, agentId), {
      method: 'POST',
      body: JSON.stringify(agentId ? { ...body, agent_id: agentId } : body),
    })
  }

  async generateSessionTitle(
    sessionId: string,
    userMessage: string,
    assistantReply?: string,
    agentId?: string
  ): Promise<{ status: string; title: string }> {
    const body: Record<string, unknown> = { user_message: userMessage, assistant_reply: assistantReply }
    if (agentId) body.agent_id = agentId
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/generate_title`, agentId), {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async clearContext(sessionId: string, agentId?: string): Promise<{ status: string; context_start_seq: number }> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, agentId), {
      method: 'POST',
      body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
    })
  }

  async getHistory(sessionId: string, page = 1, pageSize = 20, agentId?: string): Promise<HistoryPage> {
    return this.request<{ status: string } & HistoryPage>(
      this.scoped(
        `/api/history?session_id=${encodeURIComponent(sessionId)}&page=${page}&page_size=${pageSize}`,
        agentId
      )
    )
  }

  // ---------------------------------------------------------
  // 配置
  // ---------------------------------------------------------

  async getConfig(): Promise<ConfigData> {
    return this.request<{ status: string } & ConfigData>('/config')
  }

  async updateConfig(updates: Record<string, unknown>): Promise<{ status: string; applied: Record<string, unknown> }> {
    return this.request('/config', {
      method: 'POST',
      body: JSON.stringify({ updates }),
    })
  }

  // ---------------------------------------------------------
  // 车型控制台
  // ---------------------------------------------------------

  async getModels(): Promise<ModelsData> {
    return this.request<{ status: string } & ModelsData>('/api/models')
  }

  async modelsAction(action: ModelsAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/models', {
      method: 'POST',
      body: JSON.stringify(action),
    })
  }

  // ---------------------------------------------------------
  // 特工/团队名册（多特工模式）
  //
  // 传统的单代理后端仍然使用 GET /api/agents 来应答
  // 一次性名册（合成的默认代理），因此可以安全地调用
  // 无处不在； UI 决定是否基于多代理可供性
  // 在名册大小上，永远不要假设端点不存在。
  // ---------------------------------------------------------

  async getAgents(): Promise<RosterSnapshot> {
    return this.request<RosterSnapshot>('/api/agents')
  }

  async agentAction(
    body: Record<string, unknown>
  ): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/agents', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // 代理上传头像的缓存清除 URL。 `version` 应该改变
  // 每当图像被替换时， <img> 就会重新获取（名册修订版
  // 与令牌一样有效）。携带受密码保护的身份验证令牌
  // 后端，就像其他文件端点一样。
  agentAvatarUrl(agentId: string, version: string): string {
    return this.withToken(
      `${this.baseUrl}/api/agents/${encodeURIComponent(agentId)}/avatar?v=${encodeURIComponent(version)}`
    )
  }

  async uploadAgentAvatar(agentId: string, file: File): Promise<{ status: string; message?: string; revision?: string }> {
    const formData = new FormData()
    formData.append('avatar', file)
    return this.postFormData(`/api/agents/${encodeURIComponent(agentId)}/avatar`, formData)
  }

  // Agent 的可编辑核心文件 (AGENT.md / USER.md / RULE.md / MEMORY.md)。
  // 读取返回当前内容以及用于乐观的修订
  // 写入并发。
  async getAgentCoreFile(
    agentId: string,
    filename: string
  ): Promise<{ status: string; content?: string; revision?: string; message?: string }> {
    return this.request(
      `/api/agents/${encodeURIComponent(agentId)}/files/${encodeURIComponent(filename)}`
    )
  }

  async saveAgentCoreFile(
    agentId: string,
    filename: string,
    content: string,
    revision?: string
  ): Promise<{ status: string; revision?: string; message?: string }> {
    return this.request(
      `/api/agents/${encodeURIComponent(agentId)}/files/${encodeURIComponent(filename)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content, revision }),
      }
    )
  }

  // ---------------------------------------------------------
  // 渠道
  // ---------------------------------------------------------

  async getChannels(): Promise<ChannelInfo[]> {
    // 该列表按语言排序，并且保留该窗口的语言
    // 本地设置，因此可能与后端的全局设置不同。
    const data = await this.request<{ status: string; channels: ChannelInfo[] }>(
      `/api/channels?lang=${getLang()}`
    )
    return data.channels
  }

  // 全通道响应，包括多代理字段。遗留后端
  // 只是省略 `multi_agent`/`instances`，因此调用者将它们视为未定义
  // 并退回到单实例路径——没有行为改变。
  async getChannelsFull(): Promise<ChannelsResponse> {
    return this.request<ChannelsResponse>(`/api/channels?lang=${getLang()}`)
  }

  async channelAction(
    action: ChannelAction,
    channel: string,
    config?: Record<string, unknown>,
    instanceId?: string
  ): Promise<Record<string, unknown> & { status: string }> {
    // instance_id仅在多Agent模式下有意义（多实例
    // 渠道）。发送空字符串就是“创建新实例”的意思
    // 到后端；省略它完全保留旧的每种类型路径。
    const body: Record<string, unknown> = { action, channel, config }
    if (instanceId !== undefined) body.instance_id = instanceId
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // 微信二维码登录
  async getWeixinQr(): Promise<{ status: string; qrcode_url?: string; qr_image?: string; source?: string; message?: string }> {
    return this.request('/api/weixin/qrlogin')
  }

  async weixinQrAction(action: 'poll' | 'refresh'): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/weixin/qrlogin', {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
  }

  // 飞书一键注册
  async getFeishuRegister(): Promise<{ status: string; register_status?: string; qrcode_url?: string; qr_image?: string; expire_in?: number; message?: string }> {
    return this.request('/api/feishu/register')
  }

  async feishuRegisterPoll(): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/feishu/register', {
      method: 'POST',
      body: JSON.stringify({ action: 'poll' }),
    })
  }

  // ---------------------------------------------------------
  // 工具与技能
  // ---------------------------------------------------------

  async getTools(): Promise<ToolInfo[]> {
    const data = await this.request<{ status: string; tools: ToolInfo[] }>('/api/tools')
    return data.tools
  }

  // 全局技能页面保持全局（无代理范围），与网络匹配
  // 控制台：管理共享技能库。每个代理技能*选择*
  // 是在代理页面上处理的一个单独的问题，它传递一个显式的
  // agentId 来读取/写入该代理的子集。
  async getSkills(agentId?: string): Promise<SkillInfo[]> {
    const path = agentId ? `/api/skills?agent_id=${encodeURIComponent(agentId)}` : '/api/skills'
    const data = await this.request<{ status: string; skills: SkillInfo[] }>(path)
    return data.skills
  }

  async toggleSkill(name: string, action: 'open' | 'close'): Promise<ApiResult> {
    return this.request('/api/skills', {
      method: 'POST',
      body: JSON.stringify({ action, name }),
    })
  }

  /**
   * Read a skill's definition file.
   *
   * Addressed by name rather than by path: which file a name resolves to is the
   * loader's business, and a builtin skill's file sits outside the workspace.
   */
  async readSkill(name: string): Promise<SkillContent & ApiResult> {
    return this.request(`/api/skills/content?name=${encodeURIComponent(name)}`)
  }

  /**
   * Save a skill's definition file.
   *
   * Refuses a skill that ships with the installation, and answers
   * `code === 'conflict'` when the file changed since `expectedMtime` - both
   * with status 200, so the caller has to look.
   */
  async writeSkill(args: {
    name: string
    content: string
    expectedMtime?: number | null
  }): Promise<WorkspaceWriteResult & ApiResult> {
    return this.request('/api/skills/content', {
      method: 'POST',
      body: JSON.stringify({
        name: args.name,
        content: args.content,
        expected_mtime: args.expectedMtime ?? null,
      }),
    })
  }

  // ---------------------------------------------------------
  // 内存
  // ---------------------------------------------------------

  async getMemoryList(
    page = 1,
    pageSize = 20,
    category: MemoryCategory = 'memory',
    agentId?: string
  ): Promise<MemoryPage> {
    return this.request<{ status: string } & MemoryPage>(
      this.scoped(`/api/memory?page=${page}&page_size=${pageSize}&category=${category}`, agentId)
    )
  }

  /**
   * Read a memory file.
   *
   * `rel_path` is what an edit needs: memory files are addressed by name and
   * category here, but the read and write endpoints take a path. `agentId`
   * scopes the read to the right agent's workspace in a multi-agent setup.
   */
  async getMemoryDoc(
    filename: string,
    category: MemoryCategory = 'memory',
    agentId?: string
  ): Promise<MemoryDoc & ApiResult> {
    return this.request(
      this.scoped(
        `/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}`,
        agentId
      )
    )
  }

  // ---------------------------------------------------------
  // 知识
  // ---------------------------------------------------------

  async getKnowledgeList(agentId?: string): Promise<KnowledgeList> {
    return this.request<{ status: string } & KnowledgeList>(this.scoped('/api/knowledge/list', agentId))
  }

  async readKnowledge(
    path: string,
    agentId?: string
  ): Promise<{ status: string; content: string; path: string; dir?: string }> {
    return this.request(this.scoped(`/api/knowledge/read?path=${encodeURIComponent(path)}`, agentId))
  }

  async getKnowledgeGraph(agentId?: string): Promise<KnowledgeGraph> {
    return this.request<KnowledgeGraph>(this.scoped('/api/knowledge/graph', agentId))
  }

  async knowledgeAction(req: KnowledgeAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/knowledge/action', {
      method: 'POST',
      body: JSON.stringify(this.withAgent(req as unknown as Record<string, unknown>)),
    })
  }

  // 批量导入：将 .md/.txt 文件上传到目标类别（多部分）。
  async importKnowledge(
    files: File[],
    targetCategory: string,
    agentId?: string
  ): Promise<{ status: string; message?: string; payload?: KnowledgeImportPayload }> {
    const formData = new FormData()
    formData.append('target_category', targetCategory)
    formData.append('conflict_strategy', 'rename')
    const scope = (agentId ?? this.activeAgentId) || ''
    if (scope) formData.append('agent_id', scope)
    files.forEach((file) => formData.append('files', file, file.name))
    return this.postFormData('/api/knowledge/import', formData)
  }

  // ---------------------------------------------------------
  // 调度程序
  // ---------------------------------------------------------

  // 在多代理模式下，我们通过以下方式请求每个代理的聚合列表
  // 发送一个显式的空agent_id（后端将其视为“全部”），
  // 镜像网络控制台。单代理模式完全省略参数，因此
  // 旧请求未更改。
  async getSchedulerTasks(): Promise<SchedulerTask[]> {
    const path = this.activeAgentId ? '/api/scheduler?agent_id=' : '/api/scheduler'
    const data = await this.request<{ status: string; tasks: SchedulerTask[] }>(path)
    return data.tasks
  }

  // 任务突变通过其agent_id路由到所属代理的存储。路过
  // 空字符串（或在单代理模式中省略）保留旧路径。
  async runTask(taskId: string, agentId = ''): Promise<ApiResult> {
    return this.request('/api/scheduler/run', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId }),
    })
  }

  async toggleTask(taskId: string, enabled: boolean, agentId = ''): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/toggle', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, enabled, agent_id: agentId }),
    })
  }

  async updateTask(
    taskId: string,
    updates: Partial<Pick<SchedulerTask, 'name' | 'enabled' | 'schedule' | 'action'>>,
    agentId = ''
  ): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/update', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId, ...updates }),
    })
  }

  async deleteTask(taskId: string, agentId = ''): Promise<ApiResult> {
    return this.request('/api/scheduler/delete', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId }),
    })
  }

  // ---------------------------------------------------------
  // 语音
  // ---------------------------------------------------------

  async voiceAsr(audio: File | Blob): Promise<{ status: string; text?: string; audio_url?: string; message?: string }> {
    const formData = new FormData()
    // 将文件后缀与实际容器相匹配，以便后端选择
    // 右扩展（镜像网络控制台的麦克风上传）。
    const extByMime: Record<string, string> = {
      'audio/webm': 'webm',
      'audio/ogg': 'ogg',
      'audio/mp4': 'm4a',
      'audio/mpeg': 'mp3',
    }
    const mime = (audio.type || '').split(';')[0]
    const name =
      audio instanceof File && audio.name ? audio.name : `recording.${extByMime[mime] || 'webm'}`
    formData.append('file', audio, name)
    return this.postFormData('/api/voice/asr', formData)
  }

  async voiceTts(text: string, sessionId?: string): Promise<{ status: string; audio_url?: string; message?: string }> {
    return this.request('/api/voice/tts', {
      method: 'POST',
      body: JSON.stringify({ text, session_id: sessionId }),
    })
  }

  // ---------------------------------------------------------
  // 日志/版本
  // ---------------------------------------------------------

  createLogStream(): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/api/logs`))
  }

  // 完整的 run.log 作为可下载附件。查询中携带token
  // 与其他文件端点一样的字符串，因此它可以在 web_password 下工作。
  getLogDownloadUrl(): string {
    return this.withToken(`${this.baseUrl}/api/logs/download`)
  }

  async getVersion(): Promise<string> {
    const data = await this.request<{ version: string }>('/api/version')
    return data.version
  }

  // ---------------------------------------------------------
  // Auth (web_password) — 供将来使用的占位符
  // ---------------------------------------------------------

  async authCheck(): Promise<{ status: string; auth_required: boolean; authenticated?: boolean }> {
    return this.request('/auth/check')
  }

  async authLogin(password: string): Promise<ApiResult & { token?: string }> {
    const res = await this.request<ApiResult & { token?: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    })
    if (res.status === 'success' && res.token) {
      this.setAuthToken(res.token)
    }
    return res
  }

  async authLogout(): Promise<ApiResult> {
    this.setAuthToken(null)
    return this.request('/auth/logout', { method: 'POST' })
  }
}

export const apiClient = new ApiClient()
export default apiClient
