// ============================================================
// 电子桥
// ============================================================

export interface ElectronAPI {
  getBackendPort: () => Promise<number | null>
  getBackendStatus: () => Promise<string>
  /** The last backend failure, queryable so it can't be missed by timing. */
  getBackendError: () => Promise<BackendFailure | null>
  /** Data dir holding config.json and run.log (~/.cow in packaged builds). */
  getDataDir: () => Promise<string>
  restartBackend: () => Promise<boolean>
  selectDirectory: () => Promise<string | null>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  /** Open a local file with the OS default app. Resolves to '' on success. */
  openPath: (targetPath: string) => Promise<string>
  // 侦听器注册器返回取消订阅 fn 以进行清理。
  onBackendStatus: (callback: (data: BackendStatusEvent) => void) => () => void
  onBackendLog: (callback: (line: string) => void) => () => void
  windowMinimize: () => Promise<void>
  windowMaximize: () => Promise<boolean>
  windowClose: () => Promise<void>
  windowIsMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (maximized: boolean) => void) => () => void
  onMenuAction?: (callback: (action: string) => void) => () => void
  // 当前应用程序版本字符串（例如“0.0.5”）。
  getAppVersion?: () => Promise<string>
  // 登录时启动切换 (macOS + Windows)。 get 返回有效状态；
  // set 返回真实结果，以便 UI 可以显示拒绝/错误。
  getLoginItemEnabled?: () => Promise<boolean>
  setLoginItemEnabled?: (
    enabled: boolean
  ) => Promise<{ ok: boolean; enabled: boolean; error: string }>
  // 主题（来自 ~/.cow/themes 的捆绑+用户主题），内嵌图像。
  listThemes?: () => Promise<Record<string, unknown>[]>
  getThemesDir?: () => Promise<string>
  // 可选应用程序配置：首次运行默认主题+显示名称。当为空时
  // 该构建没有提供应用程序配置（标准构建）。
  getAppConfig?: () => Promise<{ defaultTheme?: string; appName?: string } | null>
  // 通过主进程进行通用 HTTPS 中继（绕过渲染器 CORS）。
  httpRelay?: (req: {
    url: string
    method?: string
    headers?: Record<string, string>
    body?: string
  }) => Promise<{ ok: boolean; status: number; headers: Record<string, string>; body: string }>
  // 自动更新。 lang（例如“zh”）将安装程序下载路由到中国 CDN。
  checkForUpdate?: (lang?: string) => Promise<void>
  downloadUpdate?: (lang?: string) => Promise<void>
  installUpdate?: () => Promise<void>
  onUpdateStatus?: (callback: (status: UpdateStatus) => void) => () => void
  // 在运行时覆盖窗口/Dock/任务栏图标和标题（缓存在
  // 发射）。由产品扩展使用；标准构建未使用。
  setAppIcon?: (iconUrl: string, icoUrl?: string) => Promise<boolean>
  setAppTitle?: (title: string) => Promise<boolean>
  // 显示本机操作系统通知；单击它会聚焦窗口并触发
  // onOpenSession 和会话 ID。
  notify?: (payload: { title?: string; body?: string; sessionId?: string; silent?: boolean }) => Promise<boolean>
  onOpenSession?: (callback: (sessionId: string) => void) => () => void
  platform: string
  // 操作系统 UI 语言（例如“zh-CN”）；用于在首次运行时默认语言。
  systemLocale?: string
}

// 镜像 src/main/updater.ts 中的 UpdateStatus。
export type UpdateStatus =
  | { state: 'checking' }
  // userInitiated：当检查来自显式“检查更新”时为 true
  // 单击；驱动已关闭的版本是否重新打开面板（请参阅商店）。
  | { state: 'available'; version: string; notes?: string; userInitiated?: boolean }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

/** Why the backend failed. Mirrors BackendErrorCode in main/python-manager.ts. */
export type BackendErrorCode =
  | 'backend_removed'
  | 'backend_missing'
  | 'backend_blocked'
  | 'backend_crashed'
  | 'backend_timeout'
  | 'backend_unresponsive'

export interface BackendFailure {
  code: BackendErrorCode
  message: string
  path?: string
}

export interface BackendStatusEvent {
  // “丢失”意味着先前准备好的后端停止应答并且主要
  // 进程正在重新启动它。
  status: 'ready' | 'error' | 'starting' | 'lost'
  port?: number
  error?: string
  // 出现“错误”：让 UI 解释具体的失败以及要解决的问题
  // 采取行动，而不是回到一个通用的句子。
  code?: BackendErrorCode
  path?: string
}

// ============================================================
// 聊天/消息/流媒体
// ============================================================

export type Role = 'user' | 'assistant' | 'system'

/** One tool call made inside a sub agent, shown under that sub agent's step. */
export interface SubStep {
  id: string
  name: string
  args?: string
  status?: string
  execution_time?: number
  error?: string
}

/** A single ordered step inside an assistant turn (matches backend history). */
export interface MessageStep {
  type: 'thinking' | 'content' | 'tool'
  content?: string
  // 工具步骤字段
  id?: string
  name?: string
  arguments?: Record<string, unknown>
  result?: string
  is_error?: boolean
  status?: string
  execution_time?: number
  /** The outcome written for a person. Rendered instead of `result`, which is
   * the form the model was handed. */
  display?: string
  /** Work done inside this step, for a tool that drives sub agents. */
  substeps?: SubStep[]
  /** Set when the tool was refused by the session's permission mode, so the UI
   * can render an actionable "adjust permissions" hint rather than a plain error. */
  permission_denied?: boolean
  /** The mode that refused the call (read-only / workspace-write / full-access). */
  permission_mode?: string
}

/** Local UI message model (superset of backend history message). */
export interface ChatMessage {
  id: string
  role: Role
  content: string
  /** Unix seconds. Backend history uses `created_at`; we normalize to `timestamp`. */
  timestamp: number
  attachments?: Attachment[]
  /** User-facing files the agent wrote during this turn, shown as file cards. */
  artifacts?: Artifact[]
  /** Ordered steps (thinking / content / tool). Preferred over legacy toolCalls. */
  steps?: MessageStep[]
  /** Legacy live-stream tool events (kept for backward compat during streaming). */
  toolCalls?: ToolCall[]
  /** Reasoning text streamed via `reasoning` SSE events. */
  reasoning?: string
  /** Sequence numbers from backend (for delete/regenerate). */
  userSeq?: number
  botSeq?: number
  /** Self-evolution bubble flag; 'divider' renders a context-cleared separator. */
  kind?: 'evolution' | 'divider'
  extras?: Record<string, unknown>
  isStreaming?: boolean
  isCancelled?: boolean
  error?: string
  /** request_id of a server-pushed (scheduler) message, used to dedupe polls. */
  pushRequestId?: string
}

export interface Attachment {
  file_path: string
  file_name: string
  /** `workspace_ref` points at an existing workspace file (dragged from the
   *  file panel or picked with `@`) and is referenced in place, not uploaded. */
  file_type: 'image' | 'video' | 'file' | 'directory' | 'workspace_ref'
  /** For `workspace_ref`: whether the reference points at a folder. */
  is_dir?: boolean
  preview_url?: string
  /** Local absolute path (set for files sent via the `send` tool) so the
   *  desktop client can open them directly with the OS default app. */
  abs_path?: string
}

// ============================================================
// 工作区文件/工件
// ============================================================

/** Coarse file classes the preview panel knows how to render. */
export type FileKind =
  | 'directory'
  | 'html'
  | 'markdown'
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'csv'
  | 'code'
  | 'office'
  | 'text'
  | 'file'

export interface WorkspaceEntry {
  name: string
  /** Workspace-relative path. */
  path: string
  is_dir: boolean
  kind: FileKind
  previewable: boolean
  size: number
  mtime: number
  abs_path?: string
  raw_url?: string
  preview_url?: string
}

/** Response of GET /api/workspace/read: the editor's initial content. */
export interface WorkspaceReadResult {
  path: string
  content: string
  /** The read stopped at the size cap, so the tail is missing. */
  truncated: boolean
  /** Bytes had to be replaced to decode as UTF-8. */
  lossy: boolean
  size: number
  /** Baseline passed back on save so the backend can detect a mid-edit rewrite. */
  mtime: number
  /** False when saving would be refused: wrong kind, truncated or lossy. */
  editable: boolean
}

/** Response of POST /api/workspace/write. */
export interface WorkspaceWriteResult {
  path?: string
  size?: number
  mtime?: number
  /** `"conflict"` when the file changed on disk since `expected_mtime`. */
  code?: string
}

export interface WorkspaceTree {
  path: string
  root: string
  entries: WorkspaceEntry[]
  truncated: boolean
}

// ============================================================
// 项目工作区（每个会话工作目录）
// ============================================================

/** A project directory the user can point a session at. */
export interface ProjectRef {
  path: string
  name: string
  /** Unix seconds of last use; present on recents. */
  ts?: number
}

/** Project picker state for a session (from /api/projects). */
export interface ProjectState {
  /** null when the session uses the default workspace (~/cow). */
  current: ProjectRef | null
  default_workspace: string
  projects_root?: string
  recents: ProjectRef[]
}

/** A user-facing file the agent wrote during a turn. */
export interface Artifact {
  abs_path: string
  rel_path: string
  file_name: string
  kind: FileKind
  previewable: boolean
  size: number
  raw_url: string
  preview_url: string
}

/** Live tool event during SSE streaming. */
export interface ToolCall {
  type: 'tool_start' | 'tool_end' | 'tool_progress'
  tool: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  result?: string
  status?: string
  execution_time?: number
}

/** All SSE event types emitted on /stream. */
export type StreamEventType =
  | 'delta'
  | 'reasoning'
  | 'tool_start'
  | 'tool_progress'
  | 'tool_end'
  | 'subagent_step'
  | 'message_end'
  | 'phase'
  | 'file_to_send'
  | 'artifact'
  | 'image'
  | 'video'
  | 'file'
  | 'text'
  | 'done'
  | 'cancelled'
  | 'voice_attach'
  | 'error'

export interface StreamEvent {
  type: StreamEventType
  content?: string
  tool?: string
  tool_call_id?: string
  arguments?: Record<string, unknown>
  status?: string
  result?: string
  /** `tool_end`: the outcome written for a person, when the tool wrote one. */
  display?: string
  execution_time?: number
  has_tool_calls?: boolean
  /** `tool_end`: true when the call was refused by the session permission mode. */
  permission_denied?: boolean
  /** `tool_end`: the mode that refused the call. */
  permission_mode?: string
  /** `subagent_step` event fields: which step of which card, and how it went. */
  card_id?: string
  step_id?: string
  phase?: 'start' | 'end'
  error?: string
  path?: string
  abs_path?: string
  file_name?: string
  file_type?: string
  web_url?: string
  audio_url?: string
  /** `artifact` event fields. */
  rel_path?: string
  kind?: FileKind
  previewable?: boolean
  size?: number
  raw_url?: string
  preview_url?: string
  request_id?: string
  timestamp?: number
  user_seq?: number
  bot_seq?: number
  message?: string
}

// ============================================================
// 会议/历史
// ============================================================

export interface SessionItem {
  session_id: string
  title: string
  created_at: number
  last_active: number
  msg_count: number
  /** User-pinned to the top of its group. */
  pinned?: boolean
  /** Bound project workspace, or null/absent for the default workspace. */
  project?: { path: string; name: string } | null
  /** The Agent whose store holds this conversation (multi-Agent backends). */
  agent?: AgentBadge
  /** Everyone in the conversation (owner first) when more than one Agent is
   *  in it; absent for an ordinary solo chat. */
  participants?: AgentBadge[]
}

/** The compact Agent identity the backend attaches to sessions and teams. */
export interface AgentBadge {
  id: string
  name: string
  avatar?: string
}

export interface SessionsPage {
  sessions: SessionItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  /** "project" once more than one distinct workspace is in play, else "time". */
  group_mode?: 'project' | 'time'
  /** Number of distinct project spaces across all sessions (decides group_mode). */
  space_count?: number
  default_workspace?: string
  /** User-defined order of project spaces; "__default__" marks the default one. */
  project_order?: string[]
}

/** Per-session model + permission overrides (from /api/sessions/{id}/settings). */
export interface SessionModelProvider {
  id: string
  label: string | { zh: string; en: string }
  models: string[]
}

export interface SessionSettingsState {
  model: {
    model: string
    provider: string
    // 有效模型的来源：对话本身的 pin、
    // 拥有 Agent 的默认模型或全局配置（按该顺序）。
    source: 'session' | 'agent' | 'global'
    global: { model: string; provider: string }
    // 拥有代理的默认模型（如果有的话）（绝不适用于默认代理）。
    agent?: { model: string; provider: string } | null
    providers: SessionModelProvider[]
  }
  permission: {
    mode: 'read-only' | 'workspace-write' | 'full-access'
    source: 'session' | 'global'
    global: string
    modes: string[]
  }
  /** Who else is on this conversation (multi-Agent backends only). */
  team?: SessionTeam
}

export interface SessionTeam {
  owner: AgentBadge
  /** Invited teammates; `available: false` marks an archived/disabled one. */
  members: (AgentBadge & { available?: boolean })[]
  /** Enabled Agents that could still be invited. */
  candidates: AgentBadge[]
}

/** Backend history message (as returned by /api/history). */
export interface HistoryMessage {
  role: Role
  content: string
  created_at: number
  steps?: MessageStep[]
  tool_calls?: Array<{ id?: string; name: string; arguments?: Record<string, unknown>; result?: string }>
  reasoning?: string
  kind?: 'evolution'
  extras?: Record<string, unknown>
  /** Files written this turn, rebuilt server-side from the write/edit steps. */
  artifacts?: Artifact[]
  /** Per-message sequence number used by delete/regenerate APIs. */
  _seq?: number
}

export interface HistoryPage {
  messages: HistoryMessage[]
  total: number
  page: number
  page_size: number
  has_more: boolean
  context_start_seq?: number
}

// ============================================================
// 配置
// ============================================================

/** A label that may be localized (some providers/channels return {zh,en}). */
export type LocalizedLabel = string | { zh: string; en: string }

export interface ReasoningOption {
  value: string
  label: string
}

export interface ReasoningCapability {
  supported: boolean
  param?: string
  default?: string
  thinking_only?: boolean
  options: ReasoningOption[]
}

export interface ProviderMeta {
  label: LocalizedLabel
  models: string[]
  reasoning?: ReasoningCapability
  reasoning_by_model?: Record<string, ReasoningCapability>
  api_base_key?: string | null
  api_base_default?: string | null
  api_base_placeholder?: string
  api_key_field?: string | null
  [k: string]: unknown
}

export interface ConfigData {
  use_agent: boolean
  title: string
  model: string
  bot_type: string
  use_linkai: boolean
  channel_type: string
  agent_max_context_tokens: number
  agent_max_context_turns: number
  agent_max_steps: number
  /** Global default permission for sessions that have not picked one. */
  agent_permission_mode?: string
  permission_modes?: string[]
  enable_thinking?: boolean
  reasoning_effort?: string
  reasoning_effort_by_model?: Record<string, string>
  subagent_enabled?: boolean
  self_evolution_enabled?: boolean
  api_bases: Record<string, string>
  api_keys: Record<string, string>
  providers: Record<string, ProviderMeta>
  web_password_masked?: string
  // 真实密码，仅返回到桌面应用程序（受信任的本地机器）所以
  // 它可以就地编辑。未定义浏览器访问。
  web_password?: string
}

// ============================================================
// 模型控制台 (/api/models)
// ============================================================

// 模型/语音条目可以是裸 ID 或带注释的 {value,hint} 对象。
export interface ModelOption {
  value: string
  hint?: string
}
export type ModelEntry = string | ModelOption

export interface ModelProvider {
  id: string
  label: LocalizedLabel
  configured: boolean
  is_custom: boolean
  custom_id?: string
  custom_name?: string
  active?: boolean
  api_key_field?: string | null
  api_base_field?: string | null
  api_key_masked?: string
  api_base?: string
  api_base_default?: string
  api_base_placeholder?: string
  models: ModelEntry[]
}

export type CapabilityKey = 'chat' | 'vision' | 'asr' | 'tts' | 'embedding' | 'image' | 'search'

// 搜索提供者被描述为对象（与其他功能不同，
// 仅列出提供商 ID）。
export interface SearchProviderMeta {
  id: string
  label: LocalizedLabel
  configured: boolean
  needs_dedicated_key: boolean
  api_key_masked?: string
}

export interface CapabilityState {
  editable?: boolean
  current_provider?: string
  current_model?: string
  current_voice?: string
  current_dim?: number | null
  suggested_provider?: string
  providers?: string[]
  // provider_models 条目是字符串 | {值，提示}
  provider_models?: Record<string, ModelEntry[]>
  // 仅 tts：由提供商键入的声音； linkai 通过型号 id 进一步键入
  provider_voices?: Record<string, ModelEntry[] | Record<string, ModelEntry[]>>
  // 视觉/图像
  strategy?: string
  user_specified_model?: string
  fallback_provider?: string
  fallback_model?: string
  // 语音合成
  reply_mode?: 'off' | 'voice_if_voice' | 'always'
  use_linkai?: boolean
  // 图像
  runtime_active?: boolean
  note?: string
  // 搜索
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
  [k: string]: unknown
}

/** Backup chat model, tried only after the primary one fails a turn. */
export interface ChatFallbackCapabilityState {
  editable?: boolean
  /** Opt-in: when false the fallback never engages. */
  enabled?: boolean
  current_provider?: string
  current_model?: string
  providers?: string[]
  provider_models?: Record<string, ModelEntry[]>
  /** How many times a single turn may switch; guards against ping-pong. */
  max_switches?: number
  /** The primary model, shown so the user sees what is being backed up. */
  primary_provider?: string
  primary_model?: string
}

export interface SearchCapabilityState {
  editable?: boolean
  providers: SearchProviderMeta[]
  strategy?: 'auto' | 'fixed' | string
  current_provider?: string
  fixed_provider?: string
  configured_providers?: string[]
  available?: boolean
}

export interface ModelsData {
  status?: string
  providers: ModelProvider[]
  capabilities: {
    chat: CapabilityState
    chat_fallback?: ChatFallbackCapabilityState
    vision: CapabilityState
    asr: CapabilityState
    tts: CapabilityState
    embedding: CapabilityState
    image: CapabilityState
    // 搜索具有更丰富的providers[]形状
    search: SearchCapabilityState
  }
}

export type ModelsAction =
  | { action: 'set_provider'; provider_id: string; api_key?: string; api_base?: string }
  | { action: 'delete_provider'; provider_id: string }
  | { action: 'set_custom_provider'; name: string; id?: string; api_base: string; api_key?: string; model?: string; make_active?: boolean }
  | { action: 'delete_custom_provider'; id: string }
  | { action: 'set_active_custom_provider'; id: string }
  // `chat_fallback` 不是一流的 CapabilityKey（它没有顶级
  // 卡），但它是通过相同的 set_capability 操作持久化的，所以它
  // 与它的选择加入字段一起在此处被接受。
  | { action: 'set_capability'; capability: CapabilityKey | 'chat_fallback'; provider_id?: string; model?: string; voice?: string; strategy?: string; provider?: string; enabled?: boolean; max_switches?: number }
  | { action: 'set_voice_reply_mode'; mode: 'off' | 'voice_if_voice' | 'always' }
  | { action: 'set_search_credential'; api_key: string }

// ============================================================
// 渠道
// ============================================================

export interface ChannelField {
  key: string
  label: string
  type: 'text' | 'secret' | 'number' | 'bool'
  value?: string | number | boolean
  default?: string | number | boolean
}

export interface ChannelInfo {
  name: string
  label: { zh: string; en: string }
  icon: string
  color: string
  active: boolean
  fields: ChannelField[]
  login_status?: string
  // 多实例字段（仅适用于每个实例一张卡的条目）
  // 当安装在多代理中时，后端返回 `data.instances`
  // 模式）。传统的每种类型卡上不存在，保持单一代理行为。
  instance_id?: string
  channel_type?: string
  agent_id?: string
  members?: string[]
}

// 完整的 /api/channels 响应。旧版单代理安装仅填充
// `channels`;多代理安装另外设置标志和 `instances`。
export interface ChannelsResponse {
  status: string
  channels: ChannelInfo[]
  multi_agent?: boolean
  multi_instance_types?: string[]
  instances?: ChannelInfo[]
}

export type ChannelAction = 'save' | 'connect' | 'disconnect'

// ============================================================
// 特工/团队名册（多特工模式）
// ============================================================

// 名册中的一个 Agent，镜像后端 AgentProfile.to_dict()。
export interface AgentProfile {
  id: string
  name: string
  workspace?: string
  enabled: boolean
  description?: string
  model?: string
  bot_type?: string
  avatar?: string
  skills?: string[]
  knowledge?: string[]
  // “共享”（读取默认代理的知识库）或“拥有”（私有目录）。
  knowledge_mode?: 'shared' | 'own'
}

// 名册 (team.json) 中存储的 channel_instances 记录。
export interface ChannelInstanceRecord {
  instance_id: string
  channel_type: string
  agent_id?: string
  members?: string[]
  credentials?: Record<string, unknown>
}

// /api/agents GET 快照。
export interface RosterSnapshot {
  status?: string
  default_agent_id: string
  agents: AgentProfile[]
  channel_instances: ChannelInstanceRecord[]
  revision: string
}

export type AgentAction =
  | 'create'
  | 'update'
  | 'archive'
  | 'delete'
  | 'set_knowledge_mode'
  | 'bind_channel_instance'

// ============================================================
// 工具/技能
// ============================================================

export interface ToolInfo {
  name: string
  description: string
}

export interface SkillInfo {
  name: string
  display_name?: string
  description: string
  source?: string
  enabled: boolean
  category?: string
}

/** Response of GET /api/skills/content: a skill's definition file. */
export interface SkillContent extends WorkspaceReadResult {
  name: string
  /** `builtin` or `custom`, by where the loader resolved the skill. */
  source: string
  /** File being shown, relative to the skill's own directory. */
  filename: string
  /**
   * True when the file is replaced from the installation on startup, so an edit
   * would not survive. Reported apart from `source`, which reads `custom` for
   * the workspace copy of a builtin skill and so cannot answer this.
   */
  ships_with_install: boolean
}

// ============================================================
// 内存
// ============================================================

export type MemoryCategory = 'memory' | 'dream' | 'evolution'

export interface MemoryItem {
  filename: string
  type: string // 全球|每日 |梦想|进化论
  size: number
  updated_at: string
}

export interface MemoryPage {
  list: MemoryItem[]
  total: number
  page: number
  page_size: number
}

/** Response of GET /api/memory/content. */
export interface MemoryDoc {
  filename: string
  /**
   * Path relative to the agent's state root, which is what the workspace read
   * and write endpoints take. Resolved by the backend because a memory file is
   * addressed by name and category, not by path.
   */
  rel_path: string
  content: string
}

// ============================================================
// 知识
// ============================================================

export interface KnowledgeFile {
  name: string
  title: string
  size: number
}

// 知识树中的目录节点（递归）。
export interface KnowledgeDir {
  dir: string
  files: KnowledgeFile[]
  children: KnowledgeDir[]
}

export interface KnowledgeList {
  root_files?: KnowledgeFile[]
  tree: KnowledgeDir[]
  stats: { pages: number; size: number }
  enabled: boolean
}

export interface KnowledgeGraph {
  nodes: Array<{ id: string; label: string; category?: string }>
  links: Array<{ source: string; target: string }>
}

// 可选的 `agent_id` 将写入范围限制为特定代理的知识库
// （由知识页面的每个代理视图使用）。单Agent模式下省略。
export type KnowledgeAction = { agent_id?: string } & (
  | { action: 'create_category'; payload: { path: string } }
  | { action: 'create_document'; payload: { path: string; content: string; overwrite?: boolean } }
  | { action: 'rename_category'; payload: { path: string; new_path: string } }
  | { action: 'delete_category'; payload: { path: string; confirm?: boolean } }
  | { action: 'delete_documents'; payload: { paths: string[] } }
  | { action: 'move_documents'; payload: { paths: string[]; target_category: string } }
)

// 批量导入的结果行（每个上传的文件一个）。
export interface KnowledgeImportResult {
  status: 'imported' | 'skipped' | 'failed'
  path?: string
  name?: string
  message?: string
}

export interface KnowledgeImportPayload {
  imported: number
  skipped: number
  failed: number
  results: KnowledgeImportResult[]
}

// ============================================================
// 调度程序
// ============================================================

export interface TaskSchedule {
  type: 'cron' | 'interval' | 'once'
  expression?: string
  seconds?: number
  run_at?: string
}

export interface TaskAction {
  type: 'send_message' | 'agent_task'
  content?: string
  task_description?: string
  receiver?: string
  receiver_name?: string
  is_group?: boolean
  channel_type?: string
}

export interface SchedulerTask {
  id: string
  name: string
  enabled: boolean
  created_at: string
  updated_at: string
  schedule: TaskSchedule
  action: TaskAction
  next_run_at?: string
  // 拥有此任务的代理。仅存在于多代理安装中；习惯于
  // 将突变路由到正确的商店并在卡上显示所有者徽章。
  agent_id?: string
}

// ============================================================
// 日志
// ============================================================

export interface LogEvent {
  type: 'init' | 'line' | 'error'
  content?: string
  message?: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
