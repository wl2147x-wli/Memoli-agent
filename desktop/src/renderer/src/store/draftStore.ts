import type { Attachment } from '../types'

// 聊天输入草稿（文本+附件）。输入位于本地
// 当用户导航时，组件状态和聊天路由会卸载 ChatPage
// 到另一页，否则会破坏键入的内容。该模块-
// 作用域变量在卸载后仍然存在，并在下次安装时恢复。
// 仅适用于渲染器进程 - 应用程序重新启动后不会持久存在。
export const chatDraft: { text: string; attachments: Attachment[] } = {
  text: '',
  attachments: [],
}
