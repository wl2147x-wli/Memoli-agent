import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Plus, Users, Trash2, Star, Upload, Check, Save, MessageSquare, Eye, Pencil } from 'lucide-react'
import { t, localizedLabel } from '../i18n'
import apiClient from '../api/client'
import type { AgentProfile, SkillInfo, SessionModelProvider } from '../types'
import { useAgentStore } from '../store/agentStore'
import { useSessionStore, sessionOwner } from '../store/sessionStore'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import { startNewChat } from '../lib/newChat'
import AgentAvatar from '../components/AgentAvatar'
import Markdown from '../components/Markdown'
import { Btn, TextInput, Modal, Toggle, Dropdown, Field, FieldTip, type DropdownOption } from './settings/primitives'

interface AgentsPageProps {
  baseUrl: string
}

type DetailTab = 'profile' | 'skills' | 'files'

/**
 * The team roster page: Agent cards on the left, a tabbed editor for the
 * selected Agent on the right (profile / skills / core files), mirroring the
 * web console's Agents view. Every write goes through `agentStore.mutate`,
 * which carries the roster revision and refreshes on success.
 *
 * This page only ever renders in multi-Agent mode (the nav entry is hidden
 * otherwise), so it can assume a real roster.
 */
const AgentsPage: React.FC<AgentsPageProps> = ({ baseUrl }) => {
  const agents = useAgentStore((s) => s.agents)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const loaded = useAgentStore((s) => s.loaded)
  const refresh = useAgentStore((s) => s.refresh)
  const mutate = useAgentStore((s) => s.mutate)

  const [selectedId, setSelectedId] = useState('')
  const [createOpen, setCreateOpen] = useState(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  // 保持有效的选择：默认为默认代理，并且永远不要指向
  // 刚刚删除的代理。
  useEffect(() => {
    if (!agents.length) return
    if (!agents.some((a) => a.id === selectedId)) {
      setSelectedId(defaultAgentId || agents[0].id)
    }
  }, [agents, defaultAgentId, selectedId])

  const selected = agents.find((a) => a.id === selectedId) || null

  // 默认特工始终领先；其余的人保持既定的顺序。
  const orderedAgents = useMemo(() => {
    const rest = agents.filter((a) => a.id !== defaultAgentId)
    const def = agents.find((a) => a.id === defaultAgentId)
    return def ? [def, ...rest] : agents
  }, [agents, defaultAgentId])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-6 pt-5 pb-3 flex-shrink-0 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-content">{t('agents_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('agents_desc')}</p>
        </div>
        <Btn variant="primary" onClick={() => setCreateOpen(true)}>
          <span className="flex items-center gap-1.5">
            <Plus size={15} />
            {t('agents_create')}
          </span>
        </Btn>
      </div>

      <div className="flex-1 overflow-hidden border-t border-default flex min-h-0">
        {!loaded ? (
          <div className="flex-1 flex items-center justify-center text-content-tertiary">
            <Loader2 size={18} className="animate-spin mr-2" />
            {t('agents_loading')}
          </div>
        ) : (
          <>
            {/* 左：名单 */}
            <div className="w-[280px] flex-shrink-0 overflow-y-auto border-r border-default p-3 space-y-2">
              {orderedAgents.map((a) => (
                <AgentCard
                  key={a.id}
                  agent={a}
                  isDefault={a.id === defaultAgentId}
                  selected={a.id === selectedId}
                  onClick={() => setSelectedId(a.id)}
                />
              ))}
            </div>

            {/* 右：所选代理的编辑器 */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col">
              {selected ? (
                <AgentDetail
                  key={selected.id}
                  agent={selected}
                  isDefault={selected.id === defaultAgentId}
                  onMutate={mutate}
                />
              ) : (
                <div className="h-full flex items-center justify-center text-content-tertiary text-sm">
                  {t('agents_empty')}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <CreateAgentModal
        open={createOpen}
        agents={agents}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false)
          setSelectedId(id)
        }}
      />
    </div>
  )
}

// 名册条目：头像、姓名、ID，加上默认的星星或存档徽章。
// UI 中没有启用/禁用开关（与 Web 控制台相同）；一个
// 通过 API 或 CLI 存档的代理仍然带有标签，因此它并不神秘。
const AgentCard: React.FC<{
  agent: AgentProfile
  isDefault: boolean
  selected: boolean
  onClick: () => void
}> = ({ agent, isDefault, selected, onClick }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center gap-3 p-2.5 rounded-card border text-left cursor-pointer transition-colors ${
      selected ? 'border-accent bg-accent-soft' : 'border-default bg-surface hover:bg-surface-2'
    } ${agent.enabled ? '' : 'opacity-60'}`}
  >
    <AgentAvatar agent={agent} size={36} />
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-1.5">
        <span className="text-sm font-medium text-content truncate">{agent.name || agent.id}</span>
        {isDefault && <Star size={12} className="text-amber-500 fill-amber-500 flex-shrink-0" />}
        {!agent.enabled && (
          <span className="px-1.5 py-px rounded-full text-[10px] bg-surface-2 text-content-tertiary flex-shrink-0">
            {t('agents_archived')}
          </span>
        )}
      </div>
      <p className="text-xs text-content-tertiary font-mono truncate">{agent.id}</p>
    </div>
  </button>
)

type Mutate = (body: Record<string, unknown>) => Promise<{ ok: boolean; message?: string }>

// 编辑器：身份标题、选项卡栏、一次一个窗格。每个窗格都拥有
// 完整剩余高度这么长的内容（技能库、核心文件）都有
// 房间而不是堆叠成一种无尽的形式。
const AgentDetail: React.FC<{
  agent: AgentProfile
  isDefault: boolean
  onMutate: Mutate
}> = ({ agent, isDefault, onMutate }) => {
  const navigate = useNavigate()
  const [tab, setTab] = useState<DetailTab>('profile')
  const [busy, setBusy] = useState(false)
  const [avatarStatus, setAvatarStatus] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const onPickAvatar = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setBusy(true)
    try {
      const res = await apiClient.uploadAgentAvatar(agent.id, file)
      if (res.status === 'success') {
        await useAgentStore.getState().refresh()
      } else {
        setAvatarStatus(res.message || t('agents_avatar_failed'))
        setTimeout(() => setAvatarStatus(''), 2400)
      }
    } catch {
      setAvatarStatus(t('agents_avatar_failed'))
      setTimeout(() => setAvatarStatus(''), 2400)
    } finally {
      setBusy(false)
    }
  }

  const startChat = () => {
    useAgentStore.getState().setActive(agent.id)
    startNewChat({ ownerId: agent.id, inheritProject: false })
    navigate('/')
  }

  const confirmDelete = async () => {
    setBusy(true)
    const res = await onMutate({ action: 'delete', id: agent.id })
    setBusy(false)
    if (res.ok) {
      setDeleteOpen(false)
    } else {
      setDeleteError(res.message || t('agents_save_failed'))
    }
  }

  const tabs: { key: DetailTab; label: string }[] = [
    { key: 'profile', label: t('agents_tab_profile') },
    { key: 'skills', label: t('agents_tab_skills') },
    { key: 'files', label: t('agents_tab_files') },
  ]

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 身份标头 */}
      <div className="px-6 pt-5 flex-shrink-0">
        <div className="flex items-start gap-4">
          <button
            onClick={() => fileRef.current?.click()}
            className="relative group cursor-pointer flex-shrink-0"
            title={t('agents_avatar_upload')}
          >
            <AgentAvatar agent={agent} size={56} />
            <span className="absolute inset-0 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
              <Upload size={16} className="text-white" />
            </span>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              hidden
              onChange={onPickAvatar}
            />
          </button>
          <div className="flex-1 min-w-0 pt-0.5">
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold text-content truncate">{agent.name || agent.id}</h3>
              {isDefault && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-amber-500/10 text-amber-600">
                  <Star size={11} className="fill-current" />
                  {t('agents_default_badge')}
                </span>
              )}
            </div>
            <p className="text-xs text-content-tertiary font-mono mt-0.5">{agent.id}</p>
            {avatarStatus && <p className="text-xs text-danger mt-1">{avatarStatus}</p>}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Btn onClick={startChat} disabled={busy}>
              <span className="flex items-center gap-1.5">
                <MessageSquare size={14} />
                {t('agents_chat')}
              </span>
            </Btn>
            {!isDefault && (
              <Btn
                variant="danger"
                onClick={() => {
                  setDeleteError('')
                  setDeleteOpen(true)
                }}
                disabled={busy}
              >
                <span className="flex items-center gap-1.5">
                  <Trash2 size={14} />
                  {t('agents_delete')}
                </span>
              </Btn>
            )}
          </div>
        </div>

        {/* 标签栏 */}
        <div className="flex items-center gap-1 mt-4 border-b border-default">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              type="button"
              onClick={() => setTab(tb.key)}
              className={`relative px-4 py-2.5 text-sm font-medium cursor-pointer transition-colors -mb-px border-b-2 ${
                tab === tb.key
                  ? 'text-accent border-accent'
                  : 'text-content-tertiary border-transparent hover:text-content-secondary'
              }`}
            >
              {tb.label}
            </button>
          ))}
        </div>
      </div>

      {/* 窗格：每个选项卡一张白卡，因此表单控件（页面灰色填充）仍然
          读取它的字段，与所有其他设置卡相同。 */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 flex flex-col">
        <div
          className={`rounded-card border border-default bg-surface p-5 flex flex-col ${
            tab === 'files' ? 'flex-1 min-h-0' : ''
          }`}
        >
          {tab === 'profile' && <AgentProfilePane agent={agent} isDefault={isDefault} onMutate={onMutate} />}
          {tab === 'skills' && <AgentSkills agent={agent} onMutate={onMutate} />}
          {tab === 'files' && <AgentCoreFiles agent={agent} />}
        </div>
      </div>

      <Modal
        open={deleteOpen}
        title={t('agents_delete_title')}
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <Btn onClick={() => setDeleteOpen(false)}>{t('cancel')}</Btn>
            <Btn variant="danger" onClick={confirmDelete} disabled={busy}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : t('agents_delete')}
            </Btn>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('agents_delete_confirm').replace('{name}', agent.name || agent.id)}
        </p>
        {deleteError && <p className="text-xs text-danger">{deleteError}</p>}
      </Modal>
    </div>
  )
}

// 个人资料选项卡：名称、职责、默认模型、知识库模式。
const AgentProfilePane: React.FC<{ agent: AgentProfile; isDefault: boolean; onMutate: Mutate }> = ({
  agent,
  isDefault,
  onMutate,
}) => {
  const [name, setName] = useState(agent.name || '')
  const [description, setDescription] = useState(agent.description || '')
  const [modelKey, setModelKey] = useState(agent.model ? `${agent.bot_type || ''}|${agent.model}` : '')
  const [status, setStatus] = useState<{ text: string; error?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)

  // 模型目录是作曲家芯片使用的目录（仅限具有
  // 键出现）。当会话设置存储有副本时，重用它；
  // 否则在这里获取它，这样即使没有打开聊天，选择器也可以工作
  // 在这次跑步中。目录不依赖于会话，只依赖于配置。
  const storeProviders = useSessionSettingsStore((s) => s.cfg?.model?.providers)
  const [fetched, setFetched] = useState<SessionModelProvider[] | null>(null)
  useEffect(() => {
    if (storeProviders || fetched) return
    let cancelled = false
    const sid = useSessionStore.getState().activeId || 'catalog'
    apiClient
      .getSessionSettings(sid)
      .then((res) => {
        if (!cancelled) setFetched(res.status === 'success' ? res.model?.providers || [] : [])
      })
      .catch(() => {
        if (!cancelled) setFetched([])
      })
    return () => {
      cancelled = true
    }
  }, [storeProviders, fetched])
  const providers = storeProviders || fetched

  const modelOptions = useMemo(() => {
    const opts: DropdownOption[] = [{ value: '', label: t('agents_model_follows_global') }]
    for (const p of providers || []) {
      for (const m of p.models || []) {
        opts.push({ value: `${p.id}|${m}`, label: m, hint: localizedLabel(p.label) })
      }
    }
    return opts
  }, [providers])
  // 供应商当前没有密钥的固定模型不在目录中；
  // 仍然显示它而不是假装代理遵循全局模型。
  const modelDisplay = modelKey && !modelOptions.some((o) => o.value === modelKey) ? modelKey.split('|')[1] : undefined

  const flash = (text: string, error = false) => {
    setStatus({ text, error })
    if (!error) setTimeout(() => setStatus(null), 1800)
  }

  const save = async () => {
    const body: Record<string, unknown> = {
      action: 'update',
      id: agent.id,
      name: name.trim(),
      description: description.trim(),
    }
    if (!isDefault) {
      const [provider, model] = modelKey.split('|')
      body.model = model || ''
      body.bot_type = provider || ''
    }
    setBusy(true)
    const res = await onMutate(body)
    setBusy(false)
    if (res.ok) {
      flash(t('agents_saved'))
      // 作曲家的模型芯片继承了该代理的默认设置：如果满足以下条件，则重新绘制它
      // 开放对话属于该代理。
      const sid = useSessionStore.getState().activeId
      if (sid && sessionOwner(sid) === agent.id) void useSessionSettingsStore.getState().refresh(sid)
    } else {
      flash(res.message || t('agents_save_failed'), true)
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <Field label={t('agents_field_name')}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder={t('agents_field_name')} />
      </Field>

      <Field label={t('agents_field_desc')} labelTip={t('agents_field_desc_hint')}>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={4}
          placeholder={t('agents_field_desc_ph')}
          className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors resize-y"
        />
      </Field>

      <Field label={t('agents_model')} hint={isDefault ? t('agents_model_default_hint') : undefined}>
        {isDefault ? (
          <div className="w-full px-3 py-2 rounded-btn border border-dashed border-strong bg-inset text-sm text-content-tertiary">
            {t('agents_model_follows_global')}
          </div>
        ) : (
          <Dropdown
            value={modelKey}
            display={modelDisplay}
            options={modelOptions}
            placeholder={t('agents_model_follows_global')}
            onChange={setModelKey}
          />
        )}
      </Field>

      {!isDefault && <KnowledgeModeField agent={agent} onMutate={onMutate} />}

      <div className="flex items-center justify-end gap-3 pt-1">
        <span
          className={`text-xs transition-opacity ${status ? 'opacity-100' : 'opacity-0'} ${
            status?.error ? 'text-danger' : 'text-accent'
          }`}
        >
          {status?.text || '\u00a0'}
        </span>
        <Btn variant="primary" onClick={save} disabled={busy}>
          {t('config_save')}
        </Btn>
      </div>
    </div>
  )
}

// 共享知识库与自己的知识库。后端的文件系统切换，所以它
// 立即应用而不是等待“保存”；乐观地描绘和
// 如果切换被拒绝，则以服务器原因回滚。
const KnowledgeModeField: React.FC<{ agent: AgentProfile; onMutate: Mutate }> = ({ agent, onMutate }) => {
  const current = agent.knowledge_mode === 'own' ? 'own' : 'shared'
  const [pending, setPending] = useState<'shared' | 'own' | null>(null)
  const [error, setError] = useState('')
  const shown = pending ?? current

  const pick = async (mode: 'shared' | 'own') => {
    if (mode === shown || pending) return
    setError('')
    setPending(mode)
    const res = await onMutate({ action: 'set_knowledge_mode', id: agent.id, mode })
    setPending(null)
    if (!res.ok) setError(res.message || t('agents_knowledge_failed'))
  }

  return (
    <Field label={t('agents_knowledge_mode')} labelTip={t('agents_knowledge_mode_hint')}>
      <div className="flex items-center gap-3">
        <Segmented
          value={shown}
          options={[
            { value: 'shared', label: t('agents_knowledge_shared') },
            { value: 'own', label: t('agents_knowledge_own') },
          ]}
          onChange={(v) => pick(v as 'shared' | 'own')}
        />
        {pending && (
          <span className="text-xs text-content-tertiary flex items-center gap-1">
            <Loader2 size={12} className="animate-spin" />
            {t('agents_knowledge_working')}
          </span>
        )}
        {error && <span className="text-xs text-danger">{error}</span>}
      </div>
    </Field>
  )
}

// 紧凑型二路开关。活跃的部分是两个主题的填充药丸
// （一个普通的白色药丸消失在黑暗主题的同样黑暗的插图上）。
const Segmented: React.FC<{
  value: string
  options: { value: string; label: string; icon?: React.ReactNode }[]
  onChange: (v: string) => void
}> = ({ value, options, onChange }) => (
  <div className="inline-flex items-center gap-0.5 p-0.5 rounded-btn border border-default bg-surface-2">
    {options.map((o) => {
      const active = o.value === value
      return (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`inline-flex items-center gap-1.5 h-[26px] px-3 rounded-[6px] text-xs font-medium cursor-pointer transition-colors ${
            active
              ? 'bg-elevated text-accent shadow-sm dark:bg-white/10'
              : 'text-content-tertiary hover:text-content-secondary'
          }`}
        >
          {o.icon}
          {o.label}
        </button>
      )
    })}
  </div>
)

// 四个可手动编辑的核心文件。 BOOTSTRAP.md 存在于磁盘上但不存在
// 用于编辑，因此有意将其排除（镜像 Web 控制台）。
const CORE_FILES: { file: string; hintKey: string }[] = [
  { file: 'AGENT.md', hintKey: 'agents_core_file_agent' },
  { file: 'USER.md', hintKey: 'agents_core_file_user' },
  { file: 'RULE.md', hintKey: 'agents_core_file_rule' },
  { file: 'MEMORY.md', hintKey: 'agents_core_file_memory' },
]

// 核心文件选项卡：文件切换器、编辑/预览切换器以及编辑器
// 占据窗格的所有高度。保存携带文件修订版，因此两个
// 编辑者不能默默地互相覆盖。
const AgentCoreFiles: React.FC<{ agent: AgentProfile }> = ({ agent }) => {
  const [file, setFile] = useState('AGENT.md')
  const [view, setView] = useState<'edit' | 'preview'>('edit')
  const [content, setContent] = useState('')
  const [revision, setRevision] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ text: string; error?: boolean } | null>(null)
  const [dirty, setDirty] = useState(false)

  // 每当代理或文件名更改时加载选取的文件。
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setStatus(null)
    apiClient
      .getAgentCoreFile(agent.id, file)
      .then((res) => {
        if (cancelled) return
        if (res.status === 'success') {
          setContent(res.content || '')
          setRevision(res.revision)
          setDirty(false)
        } else {
          setStatus({ text: res.message || t('agents_save_failed'), error: true })
        }
      })
      .catch(() => {
        if (!cancelled) setStatus({ text: t('agents_save_failed'), error: true })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [agent.id, file])

  const save = async () => {
    setBusy(true)
    try {
      const res = await apiClient.saveAgentCoreFile(agent.id, file, content, revision)
      if (res.status === 'success') {
        setRevision(res.revision)
        setDirty(false)
        setStatus({ text: t('agents_saved') })
        setTimeout(() => setStatus(null), 1800)
      } else {
        setStatus({ text: res.message || t('agents_save_failed'), error: true })
      }
    } catch {
      setStatus({ text: t('agents_save_failed'), error: true })
    } finally {
      setBusy(false)
    }
  }

  const hint = t(CORE_FILES.find((f) => f.file === file)?.hintKey || 'agents_core_file_agent')

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 工具栏：左侧文件切换器，右侧编辑/预览 */}
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex flex-wrap gap-1.5">
          {CORE_FILES.map((f) => (
            <button
              key={f.file}
              type="button"
              onClick={() => setFile(f.file)}
              title={t(f.hintKey)}
              className={`px-2.5 py-1 rounded-btn text-xs font-mono cursor-pointer transition-colors ${
                file === f.file ? 'bg-accent text-accent-contrast' : 'bg-surface-2 text-content-secondary hover:text-content'
              }`}
            >
              {f.file}
            </button>
          ))}
        </div>
        <Segmented
          value={view}
          options={[
            { value: 'edit', label: t('agents_core_edit'), icon: <Pencil size={12} /> },
            { value: 'preview', label: t('agents_core_preview'), icon: <Eye size={12} /> },
          ]}
          onChange={(v) => setView(v as 'edit' | 'preview')}
        />
      </div>

      <p className="text-xs text-content-tertiary mb-2">
        <span className="font-mono">{agent.id} / {file}</span>
        <span className="mx-1.5">·</span>
        {hint}
      </p>

      <div className="relative flex-1 min-h-[280px] flex flex-col">
        {view === 'edit' ? (
          <textarea
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setDirty(true)
            }}
            spellCheck={false}
            disabled={loading}
            className="flex-1 w-full rounded-btn border border-strong bg-inset px-3 py-2.5 text-sm font-mono text-content leading-relaxed resize-none focus:outline-none focus:border-accent transition-colors disabled:opacity-60"
            placeholder={loading ? t('agents_loading') : ''}
          />
        ) : (
          <div className="flex-1 overflow-y-auto rounded-btn border border-default bg-surface px-4 py-3">
            {content.trim() ? (
              <Markdown content={content} />
            ) : (
              <p className="text-sm text-content-tertiary">{t('agents_core_preview_empty')}</p>
            )}
          </div>
        )}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        )}
      </div>

      <div className="flex items-center justify-end gap-3 mt-3 flex-shrink-0">
        <span
          className={`text-xs transition-opacity ${status ? 'opacity-100' : 'opacity-0'} ${
            status?.error ? 'text-danger' : 'text-accent'
          }`}
        >
          {status?.text || '\u00a0'}
        </span>
        <Btn variant="primary" onClick={save} disabled={busy || loading || !dirty}>
          <span className="flex items-center gap-1.5">
            <Save size={14} />
            {t('config_save')}
          </span>
        </Btn>
      </div>
    </div>
  )
}

// 技能选项卡。 `skills == null` 表示“全部”；数组是显式子集；
// []表示没有。切换“use all”会在 null 和 [] 之间切换，因此存储的
// 价值保持紧凑。
const AgentSkills: React.FC<{ agent: AgentProfile; onMutate: Mutate }> = ({ agent, onMutate }) => {
  const [library, setLibrary] = useState<SkillInfo[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    // 全局库，因此选择器列出了已安装的所有内容。每个代理
    // 选择存储在配置文件中，而不是从此处读取。
    apiClient
      .getSkills()
      .then((skills) => {
        if (!cancelled) setLibrary(skills || [])
      })
      .catch(() => {
        if (!cancelled) setLibrary([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const useAll = agent.skills == null
  const picked = useMemo(() => new Set(useAll ? [] : agent.skills), [useAll, agent.skills])

  const toggleAll = (all: boolean) => {
    void onMutate({ action: 'update', id: agent.id, skills: all ? null : [] })
  }

  const toggleSkill = (name: string) => {
    if (useAll) return
    const next = new Set(picked)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    void onMutate({ action: 'update', id: agent.id, skills: Array.from(next) })
  }

  return (
    <div className="max-w-2xl">
      <label className="flex items-center justify-between gap-3 mb-3 pb-3 border-b border-subtle">
        <div>
          <div className="text-sm text-content">{t('agents_skills_all')}</div>
          <p className="text-xs text-content-tertiary mt-0.5">{t('agents_skills_pick')}</p>
        </div>
        <Toggle checked={useAll} onChange={toggleAll} />
      </label>

      {loading ? (
        <div className="flex items-center py-4 text-content-tertiary text-sm">
          <Loader2 size={15} className="animate-spin mr-2" />
          {t('skills_loading')}
        </div>
      ) : library.length === 0 ? (
        <p className="text-sm text-content-tertiary py-2">{t('skills_empty')}</p>
      ) : (
        <div className="space-y-1.5">
          {library.map((skill) => {
            const on = useAll || picked.has(skill.name)
            return (
              <button
                key={skill.name}
                type="button"
                disabled={useAll}
                onClick={() => toggleSkill(skill.name)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-btn text-left transition-colors ${
                  useAll ? 'opacity-60 cursor-default' : 'cursor-pointer hover:bg-surface-2'
                } ${on && !useAll ? 'bg-accent-soft' : ''}`}
              >
                <span
                  className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 border ${
                    on ? 'bg-accent border-accent text-white' : 'border-strong'
                  }`}
                >
                  {on && <Check size={11} strokeWidth={3} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-content truncate">{skill.display_name || skill.name}</div>
                  {skill.description && (
                    <div className="text-xs text-content-tertiary truncate">{skill.description}</div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// 创建模式：名称、头像、职责和要从中克隆的代理。
const CreateAgentModal: React.FC<{
  open: boolean
  agents: AgentProfile[]
  onClose: () => void
  onCreated: (id: string) => void
}> = ({ open, agents, onClose, onCreated }) => {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [cloneFrom, setCloneFrom] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // 暂存头像：代理尚不存在，因此保留选取的图像
  // 此处并在成功创建后立即上传。
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarPreview, setAvatarPreview] = useState('')
  const avatarInputRef = useRef<HTMLInputElement>(null)
  const mutate = useAgentStore((s) => s.mutate)

  useEffect(() => {
    if (open) {
      setName('')
      setDescription('')
      setCloneFrom('')
      setError('')
      setAvatarFile(null)
      setAvatarPreview('')
    }
  }, [open])

  // 当暂存图像更改或模式关闭时撤销对象 URL。
  useEffect(() => {
    return () => {
      if (avatarPreview) URL.revokeObjectURL(avatarPreview)
    }
  }, [avatarPreview])

  const onPickAvatar = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (avatarPreview) URL.revokeObjectURL(avatarPreview)
    setAvatarFile(file)
    setAvatarPreview(URL.createObjectURL(file))
  }

  // 从名称中派生一个 id，匹配 Web 控制台的 slug（小写，
  // 空格到破折号，仅限 ASCII）。后端重新验证并删除重复数据。
  const slug = (s: string) =>
    s
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError(t('agents_name_required'))
      return
    }
    const id = slug(trimmed) || `agent-${Date.now().toString(36)}`
    setBusy(true)
    const res = await mutate({
      action: 'create',
      id,
      name: trimmed,
      description: description.trim(),
      clone_from: cloneFrom || null,
    })
    if (res.ok && avatarFile) {
      // 尽力而为：头像上传失败不应撤消已创建的代理。
      try {
        await apiClient.uploadAgentAvatar(id, avatarFile)
        await useAgentStore.getState().refresh()
      } catch {
        /* 忽略； Agent存在并且可以从其详细信息设置头像 */
      }
    }
    setBusy(false)
    if (res.ok) onCreated(id)
    else setError(res.message || t('agents_create_failed'))
  }

  return (
    <Modal
      open={open}
      title={t('agents_create')}
      onClose={onClose}
      footer={
        <>
          <Btn onClick={onClose}>{t('cancel')}</Btn>
          <Btn variant="primary" onClick={submit} disabled={busy}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : t('agents_create')}
          </Btn>
        </>
      }
    >
      <div>
        <label className="block text-sm font-medium text-content-secondary mb-1.5">{t('agents_field_name')}</label>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder={t('agents_field_name')} autoFocus />
      </div>
      {/* 头像上传位于名称正下方，暂存直至创建。 */}
      <div>
        <label className="block text-sm font-medium text-content-secondary mb-1.5">{t('agents_avatar_label')}</label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => avatarInputRef.current?.click()}
            className="relative group cursor-pointer flex-shrink-0"
            title={t('agents_avatar_upload')}
          >
            {avatarPreview ? (
              <img src={avatarPreview} alt="" className="w-14 h-14 rounded-full object-cover" />
            ) : (
              <div className="w-14 h-14 rounded-full border-2 border-dashed border-strong flex items-center justify-center text-content-tertiary">
                <Upload size={18} />
              </div>
            )}
            <span className="absolute inset-0 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
              <Upload size={16} className="text-white" />
            </span>
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              hidden
              onChange={onPickAvatar}
            />
          </button>
          <p className="text-xs text-content-tertiary flex-1">{t('agents_avatar_hint')}</p>
        </div>
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-1.5">
          <label className="block text-sm font-medium text-content-secondary">{t('agents_field_desc')}</label>
          <FieldTip tip={t('agents_field_desc_hint')} />
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder={t('agents_field_desc_ph')}
          className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors resize-y"
        />
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-1.5">
          <label className="block text-sm font-medium text-content-secondary">{t('agents_clone_from')}</label>
          <FieldTip tip={t('agents_clone_hint')} />
        </div>
        <div className="flex flex-wrap gap-2">
          <CloneChip label={t('agents_clone_none')} active={!cloneFrom} onClick={() => setCloneFrom('')} icon={<Users size={13} />} />
          {agents.map((a) => (
            <CloneChip
              key={a.id}
              label={a.name || a.id}
              active={cloneFrom === a.id}
              onClick={() => setCloneFrom(a.id)}
              icon={<AgentAvatar agent={a} size={18} />}
            />
          ))}
        </div>
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
    </Modal>
  )
}

const CloneChip: React.FC<{ label: string; active: boolean; icon: React.ReactNode; onClick: () => void }> = ({
  label,
  active,
  icon,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 pl-1.5 pr-2.5 py-1 rounded-full border text-xs cursor-pointer transition-colors ${
      active ? 'border-accent bg-accent-soft text-accent' : 'border-strong text-content-secondary hover:bg-surface-2'
    }`}
  >
    {icon}
    <span className="truncate max-w-[120px]">{label}</span>
  </button>
)

export default AgentsPage
