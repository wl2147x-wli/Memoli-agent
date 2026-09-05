import { create } from 'zustand'
import apiClient from '../api/client'
import { t } from '../i18n'
import { isEditable } from '../lib/fileKind'
import { askConfirm } from './confirmStore'
import type { Artifact, WorkspaceEntry } from '../types'

const WIDTH_KEY = 'cow_workspace_width'
export const WS_MIN_WIDTH = 300
export const WS_DEFAULT_WIDTH = 440

function readWidth(): number {
  const raw = parseInt(localStorage.getItem(WIDTH_KEY) || '', 10)
  return Number.isFinite(raw) && raw >= WS_MIN_WIDTH ? raw : WS_DEFAULT_WIDTH
}

export type WorkspaceTab = 'preview' | 'files'

/**
 * State of the preview panel's text editor.
 *
 * The text itself lives in the editor component, not here: keeping it in the
 * store would re-render the whole panel on every keystroke. `dirty` is the
 * mirror the unsaved-changes guard needs, and the component only writes it when
 * the flag actually flips.
 */
export interface EditState {
  /** The file being edited; compared on save to catch a switch mid-request. */
  file: WorkspaceEntry
  /** Text the editor seeds its text area from on mount. */
  loaded: string
  /**
   * Text to compare against to decide whether anything changed. Held apart from
   * `loaded`, which the editor overwrites with work in progress when it unmounts.
   */
  baseline: string
  /** mtime the edit started from; a stale one is rejected by the backend. */
  baseMtime: number
  dirty: boolean
  saving: boolean
  error: string | null
}

interface WorkspaceState {
  open: boolean
  tab: WorkspaceTab
  width: number
  /** File currently shown in the preview tab. */
  current: WorkspaceEntry | null
  previewError: string | null
  /**
   * Set once the user closes the panel by hand. While true we stop
   * auto-opening artifacts, so the panel never fights the user.
   */
  autoOpenSuppressed: boolean
  /** Artifacts produced by the turn that is currently streaming. */
  turnArtifacts: Artifact[]
  /** Directory the files tab should jump to, with a counter so repeated
   *  requests for the same folder still trigger a reload. */
  browseDir: string | null
  browseSeq: number
  /** Session whose working dir the panel is scoped to. Passed to workspace
   *  API calls so the tree/preview resolve against the session's project. */
  sessionId: string
  /** Null unless the preview tab is showing the editor. */
  edit: EditState | null
  /**
   * Why the editor refused to open (too large, wrong encoding, read failed).
   * Shown as a banner over the preview rather than replacing it, so a file that
   * can be read but not edited is still readable.
   */
  editNotice: string | null
  dismissEditNotice: () => void

  openPanel: (tab?: WorkspaceTab) => void
  closePanel: (byUser?: boolean) => Promise<void>
  togglePanel: () => void
  setTab: (tab: WorkspaceTab) => void
  setWidth: (w: number) => void

  /** Switch the panel to a new session: drop stale file/preview state and, if
   *  open on the files tab, reload the new session's root. */
  onSessionSwitch: (sessionId: string) => void

  /** Force the files tab back to the root and reload it. Used after the project
   *  for the current session changes (select / open / new), where the session
   *  id is unchanged so onSessionSwitch would no-op. */
  reloadRoot: () => void

  preview: (target: WorkspaceEntry | Artifact | string) => Promise<void>
  openLink: (path: string) => Promise<void>
  addTurnArtifact: (a: Artifact) => void
  resetTurnArtifacts: () => void
  maybeAutoOpen: () => void

  /**
   * Ask before an action throws away unsaved edits.
   *
   * Resolves rather than taking a retry callback, so the caller stays a single
   * straight-line block and there is no window in which the editor has been
   * half torn down.
   *
   * @returns true when it is safe to proceed - either nothing was unsaved, or
   *   the user agreed to discard it (in which case the editor is already gone).
   */
  guardUnsavedEdit: () => Promise<boolean>
  /** Load the current file's text into the editor. */
  startEdit: () => Promise<void>
  setEditDirty: (dirty: boolean) => void
  /**
   * Park the in-progress text so it survives the editor being unmounted, which
   * happens whenever the user navigates off the chat route. Called from the
   * editor's cleanup, so it must be a no-op once the edit has been ended.
   */
  stashEditText: (text: string) => void
  /** Write `content` back to disk. `force` overwrites despite a conflict. */
  saveEdit: (content: string, opts?: { keepEditing?: boolean; force?: boolean }) => Promise<void>
  cancelEdit: () => Promise<void>
}

/** Artifact and WorkspaceEntry differ only in naming; normalize to an entry. */
function toEntry(a: Artifact): WorkspaceEntry {
  return {
    name: a.file_name,
    path: a.rel_path,
    is_dir: false,
    kind: a.kind,
    previewable: a.previewable,
    size: a.size,
    mtime: 0,
    abs_path: a.abs_path,
    raw_url: a.raw_url,
    preview_url: a.preview_url,
  }
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  open: false,
  tab: 'preview',
  width: readWidth(),
  current: null,
  previewError: null,
  autoOpenSuppressed: false,
  turnArtifacts: [],
  browseDir: null,
  browseSeq: 0,
  sessionId: '',
  edit: null,
  editNotice: null,

  dismissEditNotice: () => set({ editNotice: null }),

  openPanel: (tab) => set((s) => ({ open: true, tab: tab ?? s.tab })),

  // 关闭会卸载面板以及文本区域，因此与网络不同
  // 控制台没有什么可返回的 - 首先询问。
  closePanel: async (byUser) => {
    if (!(await get().guardUnsavedEdit())) return
    set((s) => ({
      open: false,
      edit: null,
      autoOpenSuppressed: byUser ? true : s.autoOpenSuppressed,
    }))
  },

  togglePanel: () => {
    const s = get()
    if (s.open) {
      s.closePanel(true)
      return
    }
    set({ open: true, autoOpenSuppressed: false, tab: s.current ? 'preview' : 'files' })
  },

  setTab: (tab) => set({ tab }),

  setWidth: (w) => {
    const next = Math.max(WS_MIN_WIDTH, Math.round(w))
    localStorage.setItem(WIDTH_KEY, String(next))
    set({ width: next })
  },

  onSessionSwitch: (sessionId) => {
    const s = get()
    if (s.sessionId === sessionId) return
    // 树/预览属于上一个会话的工作目录；放下它们。
    // 未保存的编辑由 sessionStore 中的守卫解决，该守卫在之前运行
    // 切换已提交，但仍可以取消。
    set({
      sessionId,
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: null,
      edit: null,
    })
    // 如果在文件选项卡上打开，请立即重新加载新会话的根目录。
    if (s.open && s.tab === 'files') {
      set({ browseDir: '', browseSeq: get().browseSeq + 1 })
    }
  },

  reloadRoot: () => {
    // 这里没有防护：这在提交项目绑定之后运行，所以
    // 下降只会使小组与会议脱节。的
    // 呼叫者事先询问，而开关仍然可以被取消。
    // 删除过时的预览/工件并增加浏览计数器，以便文件
    // 即使路径未更改 ('')，选项卡也会重新获取（新）根。
    set({
      current: null,
      previewError: null,
      turnArtifacts: [],
      browseDir: '',
      browseSeq: get().browseSeq + 1,
      edit: null,
    })
  },

  preview: async (target) => {
    // 打开另一个文件会替换编辑器。
    if (!(await get().guardUnsavedEdit())) return

    let entry: WorkspaceEntry | null = null
    if (typeof target === 'string') {
      try {
        entry = (await apiClient.workspaceResolve(target, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
    } else if ('rel_path' in target) {
      entry = toEntry(target)
    } else {
      entry = target
    }

    // 目录没有什么可渲染的；而是浏览它们。
    const browseIfDir = (e: WorkspaceEntry | null): boolean => {
      if (!e?.is_dir) return false
      set({
        open: true,
        tab: 'files',
        previewError: null,
        browseDir: e.path,
        browseSeq: get().browseSeq + 1,
      })
      return true
    }
    if (browseIfDir(entry)) return

    // 从历史中重建的卡牌只承载一条路径；获取签名的 URL。
    if (entry && !entry.preview_url) {
      try {
        entry = (await apiClient.workspaceResolve(entry.abs_path || entry.path, get().sessionId)).file
      } catch (e) {
        set({
          open: true,
          tab: 'preview',
          current: null,
          previewError: e instanceof Error ? e.message : String(e),
        })
        return
      }
      if (browseIfDir(entry)) return
    }

    set({ open: true, tab: 'preview', current: entry, previewError: null, edit: null })
  },

  /**
   * Open a workspace file referenced by a link in a rendered message. Agent
   * links are occasionally relative to the citing document rather than to the
   * workspace root, so fall back to a filename search before giving up.
   */
  openLink: async (path) => {
    try {
      await get().preview((await apiClient.workspaceResolve(path, get().sessionId)).file)
      return
    } catch {
      /* 进入名称搜索 */
    }

    const name = path.split('/').pop() || path
    try {
      const { results } = await apiClient.workspaceSearch(name, 10, get().sessionId)
      const hit = (results || []).find((r) => !r.is_dir && r.name === name)
      if (hit) {
        await get().preview(hit)
        return
      }
    } catch {
      /* 陷入错误状态 */
    }

    set({
      open: true,
      tab: 'preview',
      current: null,
      previewError: `${t('ws_link_not_found')}: ${path}`,
    })
  },

  addTurnArtifact: (a) =>
    set((s) =>
      s.turnArtifacts.some((x) => x.abs_path === a.abs_path)
        ? s
        : { turnArtifacts: [...s.turnArtifacts, a] }
    ),

  // 当用户发送新消息时调用。在这里清除 autoOpenSuppressed
  // 表示“关闭面板仅抑制当前回合的自动打开”；
  // 新的请求重新启用其产品的自动预览。
  resetTurnArtifacts: () => set({ turnArtifacts: [], autoOpenSuppressed: false }),

  /**
   * Auto-open policy: only when the turn produced exactly one previewable
   * artifact, and only while the user hasn't dismissed the panel by hand.
   */
  maybeAutoOpen: () => {
    const { turnArtifacts, autoOpenSuppressed, preview, edit } = get()
    const previewable = turnArtifacts.filter((a) => a.previewable)
    set({ turnArtifacts: [] })
    // 切勿替换打开的编辑器：无论哪种方式，文件卡都会保留在消息中。
    if (autoOpenSuppressed || edit || previewable.length !== 1) return
    preview(previewable[0])
  },

  guardUnsavedEdit: async () => {
    const { edit } = get()
    if (!edit?.dirty) return true
    const ok = await askConfirm({
      titleKey: 'ws_edit_discard_title',
      msgKey: 'ws_edit_discard_msg',
      okKey: 'ws_edit_discard_ok',
    })
    if (!ok) return false
    set({ edit: null })
    return true
  },

  startEdit: async () => {
    const { current, edit, sessionId } = get()
    if (edit || !current || current.is_dir || !isEditable(current.kind)) return
    // 绝对路径是明确的，这对于面板中的文件很重要
    // 到达会话的工作空间根之外（内存/知识资产
    // 当项目打开时）。
    const target = current.abs_path || current.path
    let res: Awaited<ReturnType<typeof apiClient.workspaceRead>>
    try {
      res = await apiClient.workspaceRead(target, sessionId)
    } catch (e) {
      set({ editNotice: `${t('ws_edit_load_failed')}: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    // 用户可能在请求进行时打开了另一个文件。
    // 按路径比较，而不是身份比较：保存或树刷新取代
    // 具有相同但新的对象的条目，然后进行身份检查
    // 无缘无故地中止编辑并使按钮看起来像死了一样。
    if (get().current?.path !== current.path) return
    if (res.status !== 'success' || !res.editable) {
      // 首先报告截断：部分读取也可以拆分
      // 多字节字符等回来有损，但大小是
      // 用户需要听到的原因。
      const reason = res.status !== 'success'
        ? res.message || t('ws_edit_load_failed')
        : t(res.truncated ? 'ws_edit_too_large' : res.lossy ? 'ws_edit_encoding' : 'ws_edit_unsupported')
      set({ editNotice: reason })
      return
    }
    // 文本区域将 CRLF 的值报告为 LF，因此此处进行规范化就是
    // 防止 CRLF 文件在加载时看起来已被修改。这也意味着
    // 保存会以 LF 结尾重写文件，就像 Web 控制台一样。
    const content = res.content.replace(/\r\n/g, '\n')
    set({
      open: true,
      tab: 'preview',
      previewError: null,
      editNotice: null,
      edit: {
        file: current,
        loaded: content,
        baseline: content,
        baseMtime: res.mtime,
        dirty: false,
        saving: false,
        error: null,
      },
    })
  },

  setEditDirty: (dirty) =>
    set((s) => (s.edit && s.edit.dirty !== dirty ? { edit: { ...s.edit, dirty } } : s)),

  stashEditText: (text) =>
    set((s) => (s.edit && s.edit.loaded !== text ? { edit: { ...s.edit, loaded: text } } : s)),

  saveEdit: async (content, opts) => {
    const { keepEditing = false, force = false } = opts || {}
    const { edit, sessionId } = get()
    if (!edit || edit.saving) return
    // 编写一个未修改的文件会毫无意义地影响它的运行时间。
    if (!force && !edit.dirty) {
      if (!keepEditing) set({ edit: null })
      return
    }

    set({ edit: { ...edit, saving: true, error: null } })
    try {
      const res = await apiClient.workspaceWrite({
        path: edit.file.abs_path || edit.file.path,
        content,
        session: sessionId,
        expectedMtime: force ? null : edit.baseMtime,
      })
      // 用户继续操作后进行的保存不得恢复编辑器。
      if (get().edit?.file.path !== edit.file.path) return

      if (res.code === 'conflict') {
        set((s) => (s.edit ? { edit: { ...s.edit, saving: false } } : s))
        const overwrite = await askConfirm({
          titleKey: 'ws_edit_conflict_title',
          msgKey: 'ws_edit_conflict_msg',
          okKey: 'ws_edit_overwrite',
        })
        if (overwrite) await get().saveEdit(content, { keepEditing, force: true })
        return
      }
      if (res.status !== 'success') throw new Error(res.message || 'save failed')

      // 保持条目的元数据同步，以便以后的编辑从
      // 那时我们只是写而不是陈旧的。
      const file = { ...edit.file, size: res.size ?? edit.file.size, mtime: res.mtime ?? edit.file.mtime }
      if (keepEditing) {
        set({
          current: file,
          edit: {
            ...edit,
            file,
            // 不是 `loaded`：编辑器仅从安装时生成种子，并且
            // 无论如何，重写它在这里都是无效的。
            baseline: content,
            baseMtime: res.mtime ?? edit.baseMtime,
            dirty: false,
            saving: false,
          },
        })
      } else {
        set({ current: file, edit: null })
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      set((s) => (s.edit ? { edit: { ...s.edit, saving: false, error: message } } : s))
    }
  },

  cancelEdit: async () => {
    if (!(await get().guardUnsavedEdit())) return
    set({ edit: null })
  },
}))
