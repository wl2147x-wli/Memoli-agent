import { create } from 'zustand'
import apiClient from '../api/client'
import { ownerOf, readActiveSessionId, forgetAgentOwners } from './sessionOwners'
import type { AgentProfile, ChannelInstanceRecord, RosterSnapshot } from '../types'

/**
 * The team roster and the currently selected Agent, mirroring the web console's
 * `agentCatalog` / `activeAgentId` / `defaultAgentId`.
 *
 * Robustness is the whole point of this store. The desktop client must keep
 * working for single-Agent installs that never opt into a team, and a broken or
 * legacy backend must never block startup or chat. So every load is best-effort:
 * on any failure the store simply stays in its single-Agent shape (empty
 * roster, no active id, multiAgent=false) and the rest of the UI renders exactly
 * as it did before this feature existed.
 *
 * "Multi-Agent mode" is derived, not configured: the team affordances (Agents
 * page, channel binding, the composer Agent picker) light up only when the
 * roster actually holds more than one enabled Agent. A fresh install with a
 * single synthesized default Agent looks and behaves like the old client.
 */

const ACTIVE_KEY = 'cow_active_agent'

interface AgentStore {
  /** All Agents in the roster (enabled and disabled), newest snapshot. */
  agents: AgentProfile[]
  /** The backend's default Agent id; the fallback target for everything. */
  defaultAgentId: string
  /** The Agent the console currently acts as. Always a valid enabled id, or ''. */
  activeAgentId: string
  /** Channel bindings from the roster (team.json), for the Channels page. */
  channelInstances: ChannelInstanceRecord[]
  /** Optimistic-locking token echoed back on roster writes. */
  revision: string
  /** True once the first fetch has resolved (success or failure). */
  loaded: boolean

  /** Fetch the roster. Never throws; degrades to single-Agent on error. */
  refresh: () => Promise<void>
  /** Switch the active Agent (persisted, validated, wired into the api client). */
  setActive: (id: string) => void
  /** Run a roster POST action, carrying the current revision and refreshing on
   *  success. Retries once on a stale-revision race. Returns the raw result so
   *  callers can read messages / codes. */
  mutate: (body: Record<string, unknown>) => Promise<{ ok: boolean; message?: string; code?: string }>
}

// 只有启用的代理才是用户可选择的；残疾人留在名单中
// 适用于“代理”页面，但不能成为活动对话目标。
function enabledAgents(agents: AgentProfile[]): AgentProfile[] {
  return agents.filter((a) => a.enabled)
}

// 将有效的活动 ID 推送到 API 客户端，以便范围内的端点携带
// 它。在单代理模式下，我们发送一个空 ID，客户端将其视为
// “omit agent_id” — 逐字节遗留请求。
function syncClient(activeId: string, multiAgent: boolean) {
  apiClient.setActiveAgentId(multiAgent ? activeId : '')
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: [],
  defaultAgentId: '',
  activeAgentId: '',
  channelInstances: [],
  revision: '',
  loaded: false,

  refresh: async () => {
    let snap: RosterSnapshot | null = null
    try {
      snap = await apiClient.getAgents()
    } catch {
      // 遗留/损坏的后端或网络故障：保持单代理。标记已加载
      // 因此 UI 会停止等待，但保持名册为空，这样就不会亮起任何东西。
      syncClient('', false)
      set({ loaded: true })
      return
    }
    if (!snap || snap.status === 'error' || !Array.isArray(snap.agents)) {
      syncClient('', false)
      set({ loaded: true })
      return
    }

    const agents = snap.agents
    const defaultAgentId = snap.default_agent_id || agents[0]?.id || ''
    const enabled = enabledAgents(agents)
    const multiAgent = enabled.length > 1

    // 解析活动 ID。活跃代理是开放的所有者
    // 对话，因此当会话在启动时恢复其所有者时
    // 获胜 - 否则历史记录将从错误的代理中获取
    // 储存并空空返回。没有记录所有者的恢复会话是
    // 团队前的对话，这些都与默认代理一起生活。仅有的
    // 如果没有要恢复的会话，则应用最后保留的选择。从来没有
    // 指向消失/禁用的代理（删除活动代理不得
    // 搁置控制台）。
    let active = ''
    try {
      const restoring = readActiveSessionId()
      active = restoring
        ? ownerOf(restoring) || defaultAgentId
        : localStorage.getItem(ACTIVE_KEY) || ''
    } catch {
      /* 本地存储不可用 */
    }
    if (!enabled.some((a) => a.id === active)) {
      active = defaultAgentId
      try {
        localStorage.setItem(ACTIVE_KEY, active)
      } catch {
        /* 忽略 */
      }
    }

    syncClient(active, multiAgent)
    set({
      agents,
      defaultAgentId,
      activeAgentId: active,
      channelInstances: Array.isArray(snap.channel_instances) ? snap.channel_instances : [],
      revision: snap.revision || '',
      loaded: true,
    })
  },

  setActive: (id) => {
    const { agents, activeAgentId } = get()
    if (!id || id === activeAgentId) return
    // 拒绝激活不是已启用代理的 ID。
    if (!enabledAgents(agents).some((a) => a.id === id)) return
    try {
      localStorage.setItem(ACTIVE_KEY, id)
    } catch {
      /* 忽略 */
    }
    syncClient(id, enabledAgents(agents).length > 1)
    set({ activeAgentId: id })
  },

  mutate: async (body) => {
    const send = async (retried: boolean): Promise<{ ok: boolean; message?: string; code?: string }> => {
      try {
        const res = await apiClient.agentAction({ revision: get().revision, ...body })
        if (res.status === 'success') {
          await get().refresh()
          // 删除的代理会在该客户端上留下幽灵：它的对话
          // 被删除了服务器端，但它们的所有者映射和开放
          // 会话列表仍然引用它。修剪所有者地图并重新加载
          // 列表，以便删除的代理行立即消失。
          if (body.action === 'delete' && typeof body.id === 'string') {
            forgetAgentOwners(body.id)
            try {
              const { useSessionStore } = await import('./sessionStore')
              await useSessionStore.getState().loadSessions(1)
            } catch {
              /* 会话存储不可用；列表在下次打开时刷新 */
            }
          }
          return { ok: true }
        }
        const code = res.code as string | undefined
        // 两个快速编辑可以竞争：第二个仍然带有前一个
        // 修订。重新同步并重试一次，以便快速单击即可正常工作。
        if (code === 'stale_roster' && !retried) {
          await get().refresh()
          return send(true)
        }
        return { ok: false, message: res.message as string | undefined, code }
      } catch (e) {
        return { ok: false, message: e instanceof Error ? e.message : String(e) }
      }
    }
    return send(false)
  },
}))

/** True when the install is running a team (more than one enabled Agent). */
export function isMultiAgent(): boolean {
  const { agents } = useAgentStore.getState()
  return enabledAgents(agents).length > 1
}

/** React-friendly selector for multi-Agent mode. */
export function selectMultiAgent(s: AgentStore): boolean {
  return s.agents.filter((a) => a.enabled).length > 1
}

/** Look up an Agent profile by id (any state), or undefined. */
export function findAgent(id: string): AgentProfile | undefined {
  return useAgentStore.getState().agents.find((a) => a.id === id)
}

/** The enabled Agents, in roster order. */
export function useEnabledAgents(): AgentProfile[] {
  return useAgentStore((s) => s.agents.filter((a) => a.enabled))
}

/** The enabled Agents with the default one first — the order every picker
 *  (composer, new chat, scope selectors) lists them in. */
export function enabledDefaultFirst(agents: AgentProfile[], defaultAgentId: string): AgentProfile[] {
  const enabled = enabledAgents(agents)
  const def = enabled.find((a) => a.id === defaultAgentId)
  return def ? [def, ...enabled.filter((a) => a.id !== defaultAgentId)] : enabled
}
