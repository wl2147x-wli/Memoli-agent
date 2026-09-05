import React, { useEffect, useLayoutEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useConfirmStore } from '../store/confirmStore'
import { useWorkspaceStore, type EditState } from '../store/workspaceStore'

/**
 * Plain text area editor for the preview panel.
 *
 * The text lives in the DOM rather than in React state so a keystroke doesn't
 * re-render the panel; only the dirty flag is mirrored into the store, and only
 * when it actually flips.
 */
const FileEditor: React.FC<{
  edit: EditState
  /** Owned by the panel so its Save button can read the current text. */
  textareaRef: React.RefObject<HTMLTextAreaElement>
}> = ({ edit, textareaRef: ref }) => {
  const setEditDirty = useWorkspaceStore((s) => s.setEditDirty)
  const stashEditText = useWorkspaceStore((s) => s.stashEditText)
  const saveEdit = useWorkspaceStore((s) => s.saveEdit)
  const cancelEdit = useWorkspaceStore((s) => s.cancelEdit)
  const pendingConfirm = useConfirmStore((s) => s.pending)

  // 自动对焦涵盖了普通安装。这也会使焦点重新返回一次
  // 接受它（丢弃/覆盖）的对话框已关闭，因此可以继续输入
  // 无需点击。在对话框上键入而不是运行每个渲染，
  // 这会阻止用户将注意力集中在标题按钮上。
  useLayoutEffect(() => {
    const el = ref.current
    if (!pendingConfirm && el && document.activeElement !== el) el.focus()
  }, [pendingConfirm])

  // 离开聊天路径会卸载面板；交出正在进行的工作
  // 返回商店，因此返回可以恢复它而不是丢失它。
  useEffect(() => {
    const el = ref.current
    return () => {
      if (el) stashEditText(el.value)
    }
  }, [])

  const onChange = () => setEditDirty((ref.current?.value ?? '') !== edit.baseline)

  // 原地保存会移动基线。而是从文本区域重新派生
  // 而不是信任商店的 `dirty: false`，以防用户继续输入
  // 当写入正在进行时。
  useEffect(() => {
    if (ref.current) setEditDirty(ref.current.value !== edit.baseline)
  }, [edit.baseline])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      // 像编辑器一样保存到位。标题中的“保存”按钮
      // 相反，返回到渲染的预览。
      e.preventDefault()
      saveEdit(e.currentTarget.value, { keepEditing: true })
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      cancelEdit()
      return
    }
    if (e.key === 'Tab') {
      // 否则 Tab 将焦点移出文本区域，这绝不是
      // 缩进一行代码的目的是。
      e.preventDefault()
      const el = e.currentTarget
      const { selectionStart: start, selectionEnd: end } = el
      el.value = `${el.value.slice(0, start)}    ${el.value.slice(end)}`
      el.selectionStart = el.selectionEnd = start + 4
      onChange()
    }
  }

  return (
    <div className="h-full flex flex-col">
      {edit.error && (
        <div className="shrink-0 flex items-start gap-1.5 px-3 py-2 text-[12px] text-red-500 bg-red-500/10 border-b border-default">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span className="break-all">{edit.error}</span>
        </div>
      )}
      <textarea
        ref={ref}
        // Uncontrolled: React seeds the node and then leaves the text alone, so
        // typing never round-trips through a re-render.
        defaultValue={edit.loaded}
        autoFocus
        onChange={onChange}
        onKeyDown={onKeyDown}
        spellCheck={false}
        // whitespace-pre keeps long lines on one row so code doesn't reflow;
        // the text area scrolls horizontally instead.
        className="flex-1 min-h-0 w-full p-4 bg-transparent text-content font-mono text-[12.5px] leading-relaxed border-0 outline-none resize-none whitespace-pre overflow-auto"
        style={{ tabSize: 4 }}
      />
    </div>
  )
}

export default FileEditor
