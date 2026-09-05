import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FolderOpen, Folder, House, ChevronDown, Check, Plus } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ProjectState } from '../types'
import { Modal, Btn, TextInput } from '../pages/settings/primitives'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useSessionStore } from '../store/sessionStore'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import { useUIStore } from '../store/uiStore'
import Tooltip from './Tooltip'

interface WorkspaceSelectorProps {
  sessionId: string
}

/**
 * Per-session project workspace picker. Mirrors the web console: pick the
 * default workspace (~/cow), a recent project, create a new project, or open
 * an existing directory via the native OS folder dialog. Selecting a project
 * scopes the agent's cwd, previews and `@` picker to that directory.
 */
const WorkspaceSelector: React.FC<WorkspaceSelectorProps> = ({ sessionId }) => {
  const [state, setState] = useState<ProjectState | null>(null)
  const openMenu = useSessionSettingsStore((s) => s.openMenu)
  const setOpenMenu = useSessionSettingsStore((s) => s.setOpenMenu)
  const menuOpen = openMenu === 'workspace'
  const [newOpen, setNewOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newError, setNewError] = useState('')
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const reloadRoot = useWorkspaceStore((s) => s.reloadRoot)
  const openPanel = useWorkspaceStore((s) => s.openPanel)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    try {
      const data = await apiClient.getProjects(sessionId)
      if (data.status === 'success') setState(data)
    } catch {
      /* 保持最后的状态；选择器不是关键的 */
    }
  }, [sessionId])

  // 每当活动会话发生变化时就重新加载。
  useEffect(() => {
    refresh()
  }, [refresh])

  // 当项目记录在其他地方发生更改时也会重新加载（例如，项目是
  // 从会话侧边栏重命名/删除），因此最近的内容保持同步。
  const projectsRev = useSessionStore((s) => s.projectsRev)
  useEffect(() => {
    refresh()
  }, [projectsRev, refresh])

  // 在外部单击时关闭菜单。
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpenMenu(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen, setOpenMenu])

  const current = state?.current || null
  const label = current ? current.name : t('ws_default_workspace')
  const fullPath = current ? current.path : state?.default_workspace || ''

  // 应用项目选择并显示其范围内的文件面板。的
  // 会话 ID 不变，因此我们强制 root 重新加载而不是依赖
  // 会话切换路径（无操作）。
  const applyState = (next: ProjectState) => {
    setState(next)
    openPanel('files')
    reloadRoot()
    // 显示历史记录侧边栏，以便当前会话显示在空间下方
    // 它只是绑定（镜像 Web 控制台行为）。
    useUIStore.getState().setSessionsCollapsed(false)
    // 会话列表中的分组取决于正在使用的空间数量。
    const sessionStore = useSessionStore.getState()
    sessionStore.loadSessions(1).then(() => {
      // 一个全新的会话还没有后端记录，所以上面的reload
      // 不会包括它。乐观地把它添加到原来的空间下面
      // 绑定到，以便用户看到项目内的当前对话。
      const inList = useSessionStore.getState().sessions.some((s) => s.session_id === sessionId)
      if (!inList) {
        useSessionStore
          .getState()
          .addOptimistic(sessionId, next.current ? { path: next.current.path, name: next.current.name } : null)
      }
    })
  }

  const selectProject = async (projectDir: string | null) => {
    // 重新调整面板范围会关闭所有打开的编辑器，因此请在此处解决它，而
    // 绑定尚未提交，拒绝仍然可以阻止它。
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    setOpenMenu(null)
    setBusy(true)
    try {
      const res = await apiClient.selectProject(sessionId, projectDir)
      if (res.status === 'success') applyState(res)
    } catch {
      /* 短暂的；保持当前状态不变 */
    } finally {
      setBusy(false)
    }
  }

  // 打开项目：本机操作系统文件夹选择器（Electron），然后绑定目录。
  const openProject = async () => {
    setOpenMenu(null)
    const picked = await window.electronAPI?.selectDirectory?.()
    if (picked) await selectProject(picked)
  }

  const openNewDialog = () => {
    setOpenMenu(null)
    setNewName('')
    setNewError('')
    setNewOpen(true)
  }

  const createProject = async () => {
    const name = newName.trim()
    if (!name) {
      setNewError(t('ws_sel_name_required'))
      return
    }
    if (name.includes('/') || name.includes('\\')) {
      setNewError(t('ws_sel_name_no_slash'))
      return
    }
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    setBusy(true)
    try {
      const res = await apiClient.createProject(sessionId, name)
      if (res.status === 'success') {
        setNewOpen(false)
        applyState(res)
      } else {
        setNewError(res.message || t('ws_sel_create_failed'))
      }
    } catch (e) {
      setNewError(e instanceof Error ? e.message : t('ws_sel_create_failed'))
    } finally {
      setBusy(false)
    }
  }

  const recents = state?.recents || []

  return (
    <div ref={rootRef} className="relative min-w-0">
      <Tooltip label={fullPath || t('ws_sel_tip')}>
        <button
          type="button"
          onClick={() => setOpenMenu(menuOpen ? null : 'workspace')}
          disabled={busy}
          className={`inline-flex items-center gap-1.5 h-8 px-2 rounded-btn text-xs cursor-pointer transition-colors max-w-full min-w-0 disabled:opacity-50 ${
            menuOpen
              ? 'text-accent bg-accent-soft'
              : 'text-content-secondary hover:text-accent hover:bg-accent-soft'
          }`}
        >
          <FolderOpen size={13} className="shrink-0" />
          {/* 默认工作区是隐式状态，所以那里的标签是
              只是混乱——单独显示图标并且只命名一个真实的项目。 */}
          {current && <span className="composer-chip-label truncate">{label}</span>}
          <ChevronDown size={11} className="opacity-60 shrink-0" />
        </button>
      </Tooltip>

      {menuOpen && (
        <div className="absolute bottom-full left-0 mb-1.5 w-80 max-h-[380px] overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
          <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('ws_sel_system_space')}
          </div>

          {/* 默认工作区 (~/cow) */}
          <button
            onClick={() => selectProject(null)}
            title={state?.default_workspace}
            className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
              !current ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
            }`}
          >
            <House size={14} className="shrink-0" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_default_workspace')}</span>
            {!current && <Check size={14} className="shrink-0" />}
          </button>

          {/* 项目空间：最近的项目以及所有开放/新的行动
              在一个标题下，通过分隔线与系统空间分开。 */}
          <div className="my-1 mx-1.5 border-t border-default" />
          <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
            {t('ws_sel_project_space')}
          </div>

          {recents.map((r) => {
            const active = current?.path === r.path
            return (
              <button
                key={r.path}
                onClick={() => selectProject(r.path)}
                title={r.path}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                  active ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'
                }`}
              >
                <Folder size={14} className="shrink-0" />
                <span className="flex-1 min-w-0 text-[13px] truncate">{r.name}</span>
                {active && <Check size={14} className="shrink-0" />}
              </button>
            )
          })}

          {/* 项目列表和打开/新项目操作之间的分隔线。 */}
          <div className="my-1 mx-1.5 border-t border-default" />
          <button
            onClick={openProject}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors hover:bg-surface-2 text-content"
          >
            <FolderOpen size={14} className="shrink-0 text-content-tertiary" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_sel_open')}</span>
          </button>
          <button
            onClick={openNewDialog}
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors hover:bg-surface-2 text-content"
          >
            <Plus size={14} className="shrink-0 text-content-tertiary" />
            <span className="flex-1 min-w-0 text-[13px] truncate">{t('ws_sel_new')}</span>
          </button>
        </div>
      )}

      <Modal
        open={newOpen}
        title={t('ws_sel_new_title')}
        onClose={() => setNewOpen(false)}
        footer={
          <>
            <Btn onClick={() => setNewOpen(false)}>{t('ws_sel_cancel')}</Btn>
            <Btn variant="primary" onClick={createProject} disabled={busy}>
              {t('ws_sel_create')}
            </Btn>
          </>
        }
      >
        <p className="text-xs text-content-tertiary">{t('ws_sel_new_subtitle')}</p>
        <TextInput
          autoFocus
          value={newName}
          onChange={(e) => {
            setNewName(e.target.value)
            setNewError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') createProject()
          }}
          placeholder={t('ws_sel_new_placeholder')}
        />
        {newError && <p className="text-xs text-danger">{newError}</p>}
      </Modal>
    </div>
  )
}

export default WorkspaceSelector
