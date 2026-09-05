import { create } from 'zustand'
import type { StoreApi, UseBoundStore } from 'zustand'
import { t } from '../i18n'
import { askConfirm } from './confirmStore'

/**
 * Fields a `read` has to resolve with. Both the workspace read endpoint and the
 * skills one already answer in this shape.
 */
export interface DocReadResult {
  status: string
  message?: string
  content: string
  mtime: number
  /** Whether saving would be accepted at all; the server decides. */
  editable: boolean
  /** Set when the body was cut short, or when bytes failed to decode. */
  truncated?: boolean
  lossy?: boolean
}

export interface DocWriteResult {
  status: string
  message?: string
  /** `conflict` when the file changed since the mtime the edit started from. */
  code?: string
  mtime?: number
  size?: number
}

/**
 * State of an open document's text editor.
 *
 * The text itself lives in the editor component, not here: keeping it in the
 * store would re-render the page on every keystroke. `dirty` is the mirror the
 * unsaved-changes guard needs, and the component only writes it when the flag
 * actually flips.
 */
export interface DocEdit<D> {
  doc: D
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

export interface DocEditorState<D> {
  /** Document on screen, or null while the page is showing its list. */
  doc: D | null
  /** Its text, as last read or saved; what the read-only view renders. */
  content: string
  loading: boolean
  /**
   * Message explaining why `doc` may not be edited, or null when it may be.
   * Shown instead of an edit button, so the refusal is visible before the user
   * invests any typing in it.
   */
  readonly: string | null
  edit: DocEdit<D> | null
  /** Transient failure to report at the top of the page. */
  notice: string | null

  dismissNotice: () => void
  open: (doc: D) => Promise<void>
  /** Leave the document, asking first if that would discard an edit. */
  close: () => Promise<boolean>
  /** Drop everything without asking, for a page being reset. */
  forget: () => void
  startEdit: () => Promise<void>
  setDirty: (dirty: boolean) => void
  stashText: (text: string) => void
  save: (content: string, opts?: { keepEditing?: boolean; force?: boolean }) => Promise<void>
  cancelEdit: () => Promise<void>
  /**
   * @returns true when it is safe to proceed - either nothing was unsaved, or
   *   the user agreed to discard it (in which case the editor is already gone).
   */
  guard: () => Promise<boolean>
}

export type DocEditorStore<D> = UseBoundStore<StoreApi<DocEditorState<D>>>

/**
 * @template D what identifies a document to this page.
 * @template R what its read endpoint answers, so a domain's own `refusal` sees
 *   the extra fields it reports rather than having to cast for them.
 */
interface DocEditorConfig<D, R extends DocReadResult> {
  read: (doc: D) => Promise<R>
  write: (doc: D, content: string, expectedMtime: number | null) => Promise<DocWriteResult>
  /** Stable identity, so a response that lands late can tell it is stale. */
  keyOf: (doc: D) => string
  /**
   * Why the server refused to call this document editable. Defaults to the
   * file-shaped reasons; pass one to add a domain's own (a builtin skill).
   */
  refusal?: (data: R) => string
}

/** The file-shaped reasons a document may not be edited. */
export function docRefusal(data: DocReadResult): string {
  // 先报截断：部分读取也可以分割多字节
  // 字符等回来有损，但大小是用户的原因
  // 需要听。
  if (data.truncated) return t('ws_edit_too_large')
  if (data.lossy) return t('ws_edit_encoding')
  return t('ws_edit_unsupported')
}

type AnyDocEditor = {
  getState: () => { edit: { dirty: boolean } | null; guard: () => Promise<boolean> }
}

/** Every editor built below, so a page transition can ask all of them at once. */
const registry: AnyDocEditor[] = []

/**
 * Build a store that drives one page's document viewer and editor: dirty
 * tracking, the mtime lock that stops a stale save, the discard prompt, and the
 * conflict prompt.
 *
 * Created at module scope, one per domain, so an unsaved edit survives its page
 * being unmounted by a route change - which is also what lets the navigation
 * guard find it and ask before it is thrown away.
 */
export function createDocEditorStore<D, R extends DocReadResult>(
  cfg: DocEditorConfig<D, R>
): DocEditorStore<D> {
  const refusalOf = cfg.refusal ?? docRefusal
  // 每次阅读时都会遇到碰撞，因此对用户已经阅读过的文档的响应
  // 导航离开的内容可以被删除，而不是覆盖屏幕上的内容。
  let seq = 0

  const store = create<DocEditorState<D>>((set, get) => ({
    doc: null,
    content: '',
    loading: false,
    readonly: null,
    edit: null,
    notice: null,

    dismissNotice: () => set({ notice: null }),

    open: async (doc) => {
      if (!(await get().guard())) return
      const mine = ++seq
      set({ doc, content: '', loading: true, readonly: null, edit: null, notice: null })
      try {
        const res = await cfg.read(doc)
        if (mine !== seq) return
        if (res.status !== 'success') throw new Error(res.message || t('ws_edit_load_failed'))
        set({
          content: res.content,
          loading: false,
          readonly: res.editable ? null : refusalOf(res),
        })
      } catch (e) {
        if (mine !== seq) return
        set({
          loading: false,
          notice: `${t('ws_edit_load_failed')}: ${e instanceof Error ? e.message : String(e)}`,
        })
      }
    },

    close: async () => {
      if (!(await get().guard())) return false
      seq++
      set({ doc: null, content: '', loading: false, readonly: null, edit: null })
      return true
    },

    forget: () => {
      seq++
      set({ doc: null, content: '', loading: false, readonly: null, edit: null, notice: null })
    },

    startEdit: async () => {
      const { doc, edit, readonly } = get()
      if (edit || !doc || readonly) return
      // 重新阅读而不是编辑文档时获取的副本
      // 打开：该文件可能已经存在几分钟了，由它的 mtime 决定
      // 是否允许保存落地。
      const mine = ++seq
      let res: R
      try {
        res = await cfg.read(doc)
      } catch (e) {
        set({ notice: `${t('ws_edit_load_failed')}: ${e instanceof Error ? e.message : String(e)}` })
        return
      }
      if (mine !== seq || cfg.keyOf(get().doc as D) !== cfg.keyOf(doc)) return
      if (res.status !== 'success' || !res.editable) {
        const reason = res.status !== 'success' ? res.message || t('ws_edit_load_failed') : refusalOf(res)
        set({ notice: reason, readonly: res.status === 'success' ? reason : get().readonly })
        return
      }
      // 文本区域将 CRLF 的值报告为 LF，因此此处进行规范化就是
      // 防止 CRLF 文件在加载时看起来已被修改。它还
      // 意味着保存会重写以 LF 结尾的文件，就像 Web 控制台一样。
      const content = res.content.replace(/\r\n/g, '\n')
      set({
        content,
        notice: null,
        edit: {
          doc,
          loaded: content,
          baseline: content,
          baseMtime: res.mtime,
          dirty: false,
          saving: false,
          error: null,
        },
      })
    },

    setDirty: (dirty) =>
      set((s) => (s.edit && s.edit.dirty !== dirty ? { edit: { ...s.edit, dirty } } : s)),

    stashText: (text) =>
      set((s) => (s.edit && s.edit.loaded !== text ? { edit: { ...s.edit, loaded: text } } : s)),

    save: async (content, opts) => {
      const { keepEditing = false, force = false } = opts || {}
      const { edit } = get()
      if (!edit || edit.saving) return
      // 编写一份未经修改的文档会毫无意义地影响它的运行时间。
      if (!force && !edit.dirty) {
        if (!keepEditing) set({ edit: null })
        return
      }

      const key = cfg.keyOf(edit.doc)
      set({ edit: { ...edit, saving: true, error: null } })
      try {
        const res = await cfg.write(edit.doc, content, force ? null : edit.baseMtime)
        // 用户继续操作后进行的保存不得恢复编辑器。
        const live = get().edit
        if (!live || cfg.keyOf(live.doc) !== key) return

        if (res.code === 'conflict') {
          set((s) => (s.edit ? { edit: { ...s.edit, saving: false } } : s))
          const overwrite = await askConfirm({
            titleKey: 'ws_edit_conflict_title',
            msgKey: 'ws_edit_conflict_msg',
            okKey: 'ws_edit_overwrite',
          })
          if (overwrite) await get().save(content, { keepEditing, force: true })
          return
        }
        if (res.status !== 'success') throw new Error(res.message || 'save failed')

        // 查看器读取 `content`，因此它必须随文件一起移动，无论是
        // 不是编辑保持开放状态。
        set({ content })
        if (keepEditing) {
          set((s) =>
            s.edit
              ? {
                  edit: {
                    ...s.edit,
                    // 不是 `loaded`：编辑器仅从安装时生成种子，并且
                    // 无论如何，重写它在这里都是无效的。
                    baseline: content,
                    baseMtime: res.mtime ?? s.edit.baseMtime,
                    dirty: false,
                    saving: false,
                  },
                }
              : s
          )
        } else {
          set({ edit: null })
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        set((s) => (s.edit ? { edit: { ...s.edit, saving: false, error: message } } : s))
      }
    },

    cancelEdit: async () => {
      if (!(await get().guard())) return
      set({ edit: null })
    },

    guard: async () => {
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
  }))

  registry.push(store)
  return store
}

/**
 * Ask about every document editor that has unsaved work, for a transition that
 * would unmount all of them (following a link out of the page).
 *
 * @returns false as soon as one refusal comes back, leaving the rest untouched.
 */
export async function guardDocEditors(): Promise<boolean> {
  for (const store of registry) {
    if (!(await store.getState().guard())) return false
  }
  return true
}
