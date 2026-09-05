import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { useWorkspaceStore } from './workspaceStore'
import { useAgentStore, isMultiAgent, findAgent } from './agentStore'
import { ownerOf, setOwner, forgetOwner, rememberOwners } from './sessionOwners'
import type { SessionItem } from '../types'

const ACTIVE_KEY = 'cow_session_id'
export const DEFAULT_SPACE_KEY = '__default__'

/**
 * The Agent that owns a conversation, for scoping its requests.
 *
 * For the open conversation this is, by construction, the active Agent: opening
 * a session activates its owner, and switching Agents on an empty chat re-owns
 * it. For any other row, the recorded owner (fed by the backend list and by
 * chat creation); an unknown one is the default Agent, which is where every
 * pre-team conversation lives. Empty in single-Agent mode so legacy requests
 * stay unscoped.
 */
export function sessionOwner(sessionId: string): string {
  if (!isMultiAgent()) return ''
  const { activeAgentId, defaultAgentId } = useAgentStore.getState()
  if (sessionId === useSessionStore.getState().activeId) return activeAgentId || defaultAgentId
  return ownerOf(sessionId) || defaultAgentId
}

// 打开对话使其所有者成为活跃代理 - 这就是
// 与作曲家交谈并显示其侧面板（技能、知识）。在
// 单代理模式无需切换。
function activateOwner(sessionId: string) {
  if (!isMultiAgent()) return
  const { defaultAgentId, setActive } = useAgentStore.getState()
  const owner = ownerOf(sessionId) || defaultAgentId
  if (owner) setActive(owner)
}

function badgeOf(agentId: string): SessionItem['agent'] {
  if (!agentId) return undefined
  const a = findAgent(agentId)
  return { id: agentId, name: a?.name || agentId, avatar: a?.avatar || '' }
}

interface SessionState {
  sessions: SessionItem[]
  total: number
  page: number
  hasMore: boolean
  loading: boolean
  activeId: string
  groupMode: 'project' | 'time'
  projectOrder: string[]
  /** Bumped whenever project records change (rename/delete), so other views
   *  (e.g. the workspace selector's recents) can refresh in lockstep. */
  projectsRev: number
  bumpProjects: () => void

  loadSessions: (page?: number) => Promise<void>
  loadMore: () => Promise<void>
  setActive: (id: string) => Promise<void>
  /** Start a fresh (client-side) session owned by `ownerId`, or by the active
   *  Agent when omitted. */
  newSession: (ownerId?: string) => string
  /** Re-own a not-yet-persisted conversation (the composer's Agent switch
   *  before the first message). */
  setOwner: (id: string, ownerId: string) => void
  /** The project the currently-active session is bound to, or null (default). */
  currentProject: () => { path: string; name: string } | null
  /**
   * Insert a not-yet-persisted session at the top of the list so it is visible
   * immediately (before its first message). `project` files it under the right
   * space group. No-op if the id is already present.
   */
  addOptimistic: (id: string, project?: { path: string; name: string } | null) => void
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<void>
  togglePin: (id: string) => Promise<void>
  reorderSpaces: (fromKey: string, beforeKey: string, currentOrder?: string[]) => void
}

function genId(): string {
  return `session_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

function readActive(): string {
  return localStorage.getItem(ACTIVE_KEY) || genId()
}

// 每个会话 ID 一行。偏移分页可以在以下情况下将行移回两次：
// 列表在页面之间移动，一个对话的两行都会亮起
// “选定”。第一次出现（已在屏幕上）的获胜。
function dedupe(list: SessionItem[]): SessionItem[] {
  const seen = new Set<string>()
  return list.filter((s) => {
    if (seen.has(s.session_id)) return false
    seen.add(s.session_id)
    return true
  })
}

function sortSessions(list: SessionItem[]): SessionItem[] {
  return [...list].sort((a, b) => {
    const pa = a.pinned ? 1 : 0
    const pb = b.pinned ? 1 : 0
    if (pa !== pb) return pb - pa
    return (b.last_active || 0) - (a.last_active || 0)
  })
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  total: 0,
  page: 1,
  hasMore: false,
  loading: false,
  activeId: readActive(),
  groupMode: 'time',
  projectOrder: [],
  projectsRev: 0,

  bumpProjects: () => set((s) => ({ projectsRev: s.projectsRev + 1 })),

  loadSessions: async (page = 1) => {
    set({ loading: true })
    try {
      const res = await apiClient.getSessions(page, 50)
      // 后端知道每个持续对话的所有者；保留本地的
      // 映射当前，以便正确切换到其请求的任何行范围。如果
      // 它为公开对话指定了与我们假设不同的所有者
      // （例如本地地图丢失），按照它 - 聊天页面重新加载
      // 当活动代理发生更改时，来自右侧存储的历史记录。
      rememberOwners(res.sessions || [])
      if (isMultiAgent() && (res.sessions || []).some((x) => x.session_id === get().activeId)) {
        activateOwner(get().activeId)
      }
      set((s) => ({
        sessions: page === 1 ? dedupe(res.sessions) : dedupe([...s.sessions, ...res.sessions]),
        total: res.total,
        page: res.page,
        hasMore: res.has_more,
        groupMode: res.group_mode || 'time',
        projectOrder: res.project_order || s.projectOrder,
        loading: false,
      }))
    } catch {
      set({ loading: false })
    }
  },

  loadMore: async () => {
    const { hasMore, loading, page } = get()
    if (!hasMore || loading) return
    await get().loadSessions(page + 1)
  },

  setActive: async (id) => {
    // 工作区面板的范围仅限于会话，因此切换会丢弃任何内容
    // 编辑器打开旧的。在浪费工作之前先询问一下。
    if (id !== get().activeId && !(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    localStorage.setItem(ACTIVE_KEY, id)
    activateOwner(id)
    set({ activeId: id })
  },

  newSession: (ownerId) => {
    const id = genId()
    if (isMultiAgent()) {
      const owner = ownerId || useAgentStore.getState().activeAgentId
      if (owner) setOwner(id, owner)
      activateOwner(id)
    }
    localStorage.setItem(ACTIVE_KEY, id)
    set({ activeId: id })
    return id
  },

  setOwner: (id, ownerId) => {
    if (!isMultiAgent() || !ownerId) return
    setOwner(id, ownerId)
    set((s) => ({
      sessions: s.sessions.map((sess) => (sess.session_id === id ? { ...sess, agent: badgeOf(ownerId) } : sess)),
    }))
    if (get().activeId === id) activateOwner(id)
  },

  currentProject: () => {
    const { activeId, sessions } = get()
    return sessions.find((s) => s.session_id === activeId)?.project ?? null
  },

  addOptimistic: (id, project) => {
    set((s) => {
      const existing = s.sessions.find((sess) => sess.session_id === id)
      // 已经存在：只需将其重新归档到给定空间下（例如，用户
      // 创建项目后将新的聊天绑定到项目）并将其浮动到顶部。
      if (existing) {
        const rest = s.sessions.filter((sess) => sess.session_id !== id)
        return { sessions: [{ ...existing, project: project ?? null }, ...rest] }
      }
      const now = Math.floor(Date.now() / 1000)
      const item: SessionItem = {
        session_id: id,
        title: t('session_new'),
        created_at: now,
        last_active: now,
        msg_count: 0,
        pinned: false,
        project: project ?? null,
        agent: badgeOf(ownerOf(id)),
      }
      return { sessions: [item, ...s.sessions] }
    })
  },

  rename: async (id, title) => {
    await apiClient.renameSession(id, title, sessionOwner(id))
    set((s) => ({
      sessions: s.sessions.map((sess) => (sess.session_id === id ? { ...sess, title } : sess)),
    }))
  },

  remove: async (id) => {
    await apiClient.deleteSession(id, sessionOwner(id))
    forgetOwner(id)
    set((s) => ({ sessions: s.sessions.filter((sess) => sess.session_id !== id) }))
    if (get().activeId === id) get().newSession()
  },

  togglePin: async (id) => {
    const entry = get().sessions.find((s) => s.session_id === id)
    if (!entry) return
    const pinned = !entry.pinned
    set((s) => ({
      sessions: sortSessions(
        s.sessions.map((sess) => (sess.session_id === id ? { ...sess, pinned } : sess))
      ),
    }))
    try {
      const res = await apiClient.setSessionPinned(id, pinned, sessionOwner(id))
      if (res.status !== 'success') throw new Error(res.message || 'pin failed')
    } catch {
      set((s) => ({
        sessions: sortSessions(
          s.sessions.map((sess) => (sess.session_id === id ? { ...sess, pinned: !pinned } : sess))
        ),
      }))
    }
  },

  reorderSpaces: (fromKey, beforeKey, currentOrder) => {
    const { projectOrder, sessions, groupMode } = get()
    // 优先选择呼叫者当前显示的组顺序（通过
    // buildGroups），因此拖动与用户看到的内容相匹配，并且永远不会倾斜
    // 通过位于阵列顶部的新创建的会话。回落
    // 到保存的顺序，然后到派生的顺序。
    const current =
      currentOrder && currentOrder.length
        ? [...currentOrder]
        : projectOrder.length
          ? [...projectOrder]
          : Array.from(
              new Set(sessions.map((s) => s.project?.path || DEFAULT_SPACE_KEY))
            )
    // 包括保存的订单尚不知道的任何可见键。
    if (groupMode === 'project') {
      for (const s of sessions) {
        const k = s.project?.path || DEFAULT_SPACE_KEY
        if (!current.includes(k)) current.push(k)
      }
      if (!current.includes(DEFAULT_SPACE_KEY) && sessions.some((s) => !s.project?.path)) {
        current.unshift(DEFAULT_SPACE_KEY)
      }
    }
    const order = current.filter((k) => k !== fromKey)
    const idx = order.indexOf(beforeKey)
    if (idx < 0) order.push(fromKey)
    else order.splice(idx, 0, fromKey)
    set({ projectOrder: order })
    apiClient.setProjectsOrder(order).catch(() => {
      /* 保持乐观秩序；下一个 loadSessions 将协调 */
    })
  },
}))
